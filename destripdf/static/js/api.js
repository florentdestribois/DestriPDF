// Accès à l'API locale. Les chemins sont relatifs : le jeton secret fait partie de l'URL de la page.

export class ApiError extends Error {
  constructor(message, code = 'error', status = 0, data = null) {
    super(message);
    this.code = code;
    this.status = status;
    this.data = data || {};
  }
}

async function parse(response) {
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    throw new ApiError((data && data.error) || `Erreur ${response.status}`, (data && data.code) || 'error', response.status, data);
  }
  return data || {};
}

export const Api = {
  async get(path) {
    let response;
    try {
      response = await fetch(path, { cache: 'no-store' });
    } catch {
      throw new ApiError("DestriPDF ne répond plus : relancez l'application.", 'offline');
    }
    return parse(response);
  },

  async post(path, body = {}, method = 'POST') {
    let response;
    try {
      response = await fetch(path, {
        method,
        headers: { 'Content-Type': 'application/json', 'X-DestriPDF': '1' },
        body: JSON.stringify(body),
      });
    } catch {
      throw new ApiError("DestriPDF ne répond plus : relancez l'application.", 'offline');
    }
    return parse(response);
  },

  async upload(path, blob, contentType = 'application/pdf') {
    let response;
    try {
      response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': contentType, 'X-DestriPDF': '1' },
        body: blob,
      });
    } catch {
      throw new ApiError("DestriPDF ne répond plus : relancez l'application.", 'offline');
    }
    return parse(response);
  },

  async del(path) {
    return this.post(path, {}, 'DELETE');
  },
};
