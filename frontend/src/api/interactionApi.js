async function callInteractionApi(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    const body = await response.json();
    if (!response.ok || body.code !== 0) {
        throw new Error(body.message || `Interaction request failed (${response.status})`);
    }
    return body.data || {};
}

export async function listPendingInteractions(tabId) {
    const data = await callInteractionApi(`/api/interactions/pending?tab_id=${encodeURIComponent(tabId)}`);
    return Array.isArray(data.items) ? data.items : [];
}

export async function answerInteraction(interactionId, payload) {
    return callInteractionApi(`/api/interactions/${encodeURIComponent(interactionId)}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
}
