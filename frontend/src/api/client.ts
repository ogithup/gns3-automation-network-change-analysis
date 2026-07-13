export const apiBaseUrl = "http://127.0.0.1:8000";

export async function fetchHealth() {
  const response = await fetch(`${apiBaseUrl}/health`);

  if (!response.ok) {
    throw new Error("Backend health request failed");
  }

  return response.json() as Promise<{
    status: string;
    service: string;
    environment: string;
  }>;
}

