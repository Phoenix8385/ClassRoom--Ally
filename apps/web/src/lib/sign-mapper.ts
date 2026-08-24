export type SignAction =
  | {
      type: "clip";
      word: string;
      path: string;
      durationMs: number;
    }
  | {
      type: "fingerspell";
      word: string;
    };

type SignManifest = Record<
  string,
  {
    path: string;
    size_bytes: number;
    duration_ms: number;
    category: string;
  }
>;

let manifest: SignManifest | null = null;

export async function loadSignManifest(): Promise<SignManifest> {
  if (manifest) return manifest;

  const response = await fetch("/signs/manifest.json");

  if (!response.ok) {
    throw new Error(
      `Failed to load sign manifest: ${response.status}`
    );
  }

  manifest = await response.json();
  return manifest;
}

export async function mapGlossToSigns(
  gloss: string
): Promise<SignAction[]> {
  const signs = await loadSignManifest();

  const normalized = gloss
    .trim()
    .toLowerCase()
    .replace(/[.,!?;:]/g, "");

  if (!normalized) {
    return [];
  }

  const words = normalized.split(/\s+/);
  const actions: SignAction[] = [];

  let i = 0;

  while (i < words.length) {
    // Check two-word signs first.
    if (i + 1 < words.length) {
      const phrase = `${words[i]} ${words[i + 1]}`;

      if (signs[phrase]) {
        actions.push({
          type: "clip",
          word: phrase,
          path: signs[phrase].path,
          durationMs: signs[phrase].duration_ms,
        });

        i += 2;
        continue;
      }
    }

    const word = words[i];
    const sign = signs[word];

    if (sign) {
      actions.push({
        type: "clip",
        word,
        path: sign.path,
        durationMs: sign.duration_ms,
      });
    } else {
      actions.push({
        type: "fingerspell",
        word,
      });
    }

    i++;
  }

  return actions;
}