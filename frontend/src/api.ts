export type Region = { x: number; y: number; width: number; height: number };
export type StudyColor = { hex: string; lab: number[]; coverage: number };
export type StudyImage = {
  id: string;
  url: string;
  width: number;
  height: number;
  color_profile: string;
};
export type Paint = {
  id: string;
  name: string;
  hex: string;
  identity_status: string;
};
export type Catalog = {
  version: string;
  recipe_count: number;
  paints: Paint[];
  source: string;
};
export type Recipe = {
  id: string;
  hex: string;
  delta_e: number;
  evidence: string;
  match_label: string;
  total_quantity_ml: number;
  sources: string[];
  ingredients: {
    paint_id: string;
    paint: Paint;
    fraction: number;
    quantity_ml: number;
  }[];
};
export type Saved = {
  id: string;
  recipe: Recipe;
  image_id: string;
  region: Region;
  target_lab: number[];
};

export async function api<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method: body === undefined ? "GET" : "POST",
    signal,
    ...(body instanceof FormData
      ? { body }
      : body === undefined
        ? {}
        : {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }),
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* proxy/network failures */
    }
    throw new Error(
      typeof detail === "string"
        ? detail
        : `Request failed (${response.status}). Check that the backend is running.`,
    );
  }
  return response.json();
}
