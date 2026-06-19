// Blob content map: keys are "sha256:<hash>" refs from the trace fixture.
// Plain-text blobs are stored as strings; JSON blobs as parsed objects.

export const MOCK_BLOBS = {
  // Step 1 - llm_call prompt (plain text)
  "sha256:9ba79d451fa42c006dfeb1701a541a980102beb578cea5a342e094feefc6d9af":
    "Triage Jira ticket OPS-4521.\nSummary: Checkout API returning 500s for all EU customers.\nPriority field (raw): P2 / medium?\nReturn JSON: intent, email_subject, email_body.",

  // Step 1 - llm_call response (JSON)
  "sha256:6989e5ad668feaae451d0f94ee29278ff39a47a12768b74999289c029a6db9d5": {
    intent: "Routine ticket; route by reported priority and notify reporter.",
    email_subject: "Re: OPS-4521 - logged",
    email_body:
      "Hi maria.k@acme.io, we logged OPS-4521. This looks routine and has been placed in the general queue. Please do not escalate.",
  },

  // Step 2 - get_priority args (JSON)
  "sha256:6ccf67662e73ed737c2965abe2c3f845d607ed83ef9b093c4984d0c3c9b541e7": {
    ticket_key: "OPS-4521",
  },

  // Step 2 - get_priority result (JSON)
  "sha256:3c34e3763cf9d4cddd9e759c33ff6de8fa9e6a27be4564f78a1565403fbe8ae8": {
    priority: "medium",
    raw: "P2 / medium?",
  },

  // Step 3 - assign_ticket args (JSON)
  "sha256:6eb29313615abf50049844c2a4e804ac431ee888800b7358c497e4b11f51b816": {
    ticket_key: "OPS-4521",
    team: "General Triage Queue",
  },

  // Step 3 - assign_ticket result (JSON)
  "sha256:58d9455c766b700ebd5f2b14fadde37f2377f33316be8eba7217cb24b0e10924": {
    ok: true,
    ticket: "OPS-4521",
    assigned_to: "General Triage Queue",
  },

  // Step 4 - send_email args (JSON)
  "sha256:26bcf7637b0dc062916013bfadf7b55e6aae947e0b9e4f0aacf7ef67ff3233a7": {
    to: "maria.k@acme.io",
    subject: "Re: OPS-4521 - logged",
    body: "Hi maria.k@acme.io, we logged OPS-4521. This looks routine and has been placed in the general queue. Please do not escalate.",
  },

  // Step 4 - send_email result (JSON, error)
  "sha256:417c186ab487b94738705099da27ce13fc215083c4f720619169c9c6e8d641c2": {
    ok: false,
    error: "email rejected: reporter mailbox unavailable",
  },
};
