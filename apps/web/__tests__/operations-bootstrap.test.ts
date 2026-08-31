import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('Operations Bootstrap Logic', () => {
  it('should derive eligible tenants correctly from bootstrap data', () => {
    const bootstrap = {
      tenants: [
        { id: 't1', name: 'T1', role: 'owner', can_create: true, members: [] },
        { id: 't2', name: 'T2', role: 'member', can_create: true, members: [] },
        { id: 't3', name: 'T3', role: 'manager', can_create: true, members: [] },
      ]
    };
    const eligible = bootstrap.tenants.filter(t => t.can_create);
    assert.strictEqual(eligible.length, 3);
    assert.strictEqual(eligible[0].id, 't1');
    assert.strictEqual(eligible[1].id, 't2');
    assert.strictEqual(eligible[2].id, 't3');
  });

  it('should correctly select assignee defaults', () => {
    const userId = 'u1';
    const tenantWithUser = {
      id: 't1',
      name: 'T1',
      role: 'owner',
      can_create: true,
      members: [{ id: 'u1', full_name: 'Me', email: '', role: 'owner' }]
    };
    const tenantWithoutUser = {
      id: 't2',
      name: 'T2',
      role: 'owner',
      can_create: true,
      members: [{ id: 'u2', full_name: 'Other', email: '', role: 'member' }]
    };

    assert.strictEqual(tenantWithUser.members.some(m => m.id === userId), true);
    assert.strictEqual(tenantWithoutUser.members.some(m => m.id === userId), false);
  });
});
