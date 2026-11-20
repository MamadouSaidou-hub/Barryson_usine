import type { components } from "./schema";

export type S = components["schemas"];

export class ErreurApi extends Error {
  constructor(
    public statut: number,
    message: string,
    public corps?: Record<string, unknown>,
  ) {
    super(message);
  }
}

// Jeton anti-CSRF : renvoye a la connexion et par /api/auth/moi, garde en memoire seulement
// (jamais dans le stockage du navigateur) et envoye avec toute requete qui modifie quelque chose.
let csrf = "";
export const definirCsrf = (valeur: string) => {
  csrf = valeur;
};

let surSessionPerdue: (() => void) | null = null;
export const ecouterSessionPerdue = (rappel: () => void) => {
  surSessionPerdue = rappel;
};

function message(corps: unknown, statut: number): string {
  const detail = (corps as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e: { loc?: (string | number)[]; msg?: string }) => `${(e.loc ?? []).slice(1).join(" › ")} : ${e.msg}`)
      .join(" ; ");
  }
  if (statut === 403) return "Accès refusé.";
  return `Erreur ${statut}`;
}

export async function appeler<T>(
  methode: "GET" | "POST" | "PUT" | "PATCH",
  chemin: string,
  corps?: unknown,
  options: { garderSession?: boolean } = {},
): Promise<T> {
  const entetes: Record<string, string> = {};
  if (corps !== undefined) entetes["Content-Type"] = "application/json";
  if (methode !== "GET") entetes["X-CSRF-Token"] = csrf;
  const reponse = await fetch(chemin, {
    method: methode,
    headers: entetes,
    credentials: "same-origin",
    body: corps === undefined ? undefined : JSON.stringify(corps),
  });
  if (reponse.status === 204) return undefined as T;
  let donnees: Record<string, unknown> | undefined;
  try {
    donnees = await reponse.json();
  } catch {
    donnees = undefined;
  }
  if (!reponse.ok) {
    if (reponse.status === 401 && !options.garderSession) surSessionPerdue?.();
    throw new ErreurApi(reponse.status, message(donnees, reponse.status), donnees);
  }
  return donnees as T;
}

export const lire = <T>(chemin: string) => appeler<T>("GET", chemin);
export const envoyer = <T>(chemin: string, corps?: unknown) => appeler<T>("POST", chemin, corps ?? {});
export const remplacer = <T>(chemin: string, corps: unknown) => appeler<T>("PUT", chemin, corps);
export const modifier = <T>(chemin: string, corps: unknown) => appeler<T>("PATCH", chemin, corps);

export function requete(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(params)) {
    if (valeur !== undefined && valeur !== null && valeur !== "") p.set(cle, String(valeur));
  }
  const texte = p.toString();
  return texte ? `?${texte}` : "";
}
