"""Redacted, deterministic samples for the Content Manager response contract.

The samples intentionally omit optional display-only fields.  Keeping these
fixtures small makes a provider response-shape change obvious in review and
keeps the live-provider test from ever needing to print model output.
"""

COMPLETE = {
    "status": "complete",
    "document": "العنوان: تحديث داخلي\nالنص: يرجى الاطلاع على التحديث.",
}

NEEDS_INFORMATION = {
    "status": "needs_information",
    "ui": {
        "fields": [
            {
                "id": "audience",
                "label": "الجمهور",
                "type": "text",
            }
        ]
    },
}

OUT_OF_SCOPE = {
    "status": "out_of_scope",
    "redirect_message": "هذا المساعد مخصص لإعداد وتحرير مستندات العمل.",
}

PROVIDER_CONTRACT_SAMPLES: dict[str, dict[str, object]] = {
    "complete": COMPLETE,
    "needs_information": NEEDS_INFORMATION,
}

RESPONSE_CONTRACT_SAMPLES: dict[str, dict[str, object]] = {
    **PROVIDER_CONTRACT_SAMPLES,
    "out_of_scope": OUT_OF_SCOPE,
}