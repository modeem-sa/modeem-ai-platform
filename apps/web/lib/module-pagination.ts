export interface PaginationPage<T> {
  records: T[];
  offset: number;
  returned_count: number;
  has_more: boolean;
  next_offset: number | null;
}

export const MAX_MODULE_RECORDS = 5000;
export const MAX_MODULE_PAGES = 200;

export async function collectAllModulePages<T extends { id: number; name: string }>(
  fetchPage: (offset: number) => Promise<PaginationPage<T>>,
): Promise<T[]> {
  const records = new Map<string, T>();
  const visitedOffsets = new Set<number>();
  let offset = 0;

  for (let pageNumber = 0; pageNumber < MAX_MODULE_PAGES; pageNumber += 1) {
    if (visitedOffsets.has(offset)) {
      throw new Error("Invalid module pagination: repeated offset");
    }
    visitedOffsets.add(offset);
    const page = await fetchPage(offset);
    if (
      !Array.isArray(page.records)
      || page.offset !== offset
      || page.returned_count !== page.records.length
      || typeof page.has_more !== "boolean"
    ) {
      throw new Error("Invalid module pagination response");
    }
    for (const record of page.records) {
      records.set(record.name, record);
      if (records.size > MAX_MODULE_RECORDS) {
        throw new Error("Module inventory exceeds the safe limit");
      }
    }
    if (!page.has_more) {
      return [...records.values()].sort(
        (left, right) => left.name.localeCompare(right.name) || left.id - right.id,
      );
    }
    if (
      !Number.isInteger(page.next_offset)
      || page.next_offset === null
      || page.next_offset <= offset
    ) {
      throw new Error("Invalid module pagination: next offset did not advance");
    }
    offset = page.next_offset;
  }
  throw new Error("Module pagination exceeded the safe page limit");
}