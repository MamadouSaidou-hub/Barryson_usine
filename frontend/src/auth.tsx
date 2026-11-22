import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { appeler, definirCsrf, ecouterSessionPerdue, ErreurApi, type S } from "./api";

type Session = S["ReponseSession"];

interface Contexte {
  session: Session | null;
  chargement: boolean;
  /** Renvoie "code_requis" quand le mot de passe est bon mais qu'un code a 6 chiffres est exige. */
  connecter: (identifiant: string, motDePasse: string, code?: string) => Promise<"ok" | "code_requis">;
  deconnecter: () => Promise<void>;
  actualiser: () => Promise<void>;
  appliquer: (session: Session) => void;
  peut: (permission: string) => boolean;
  /** Vrai si l'utilisateur a l'un de ces droits. */
  peutUn: (...permissions: string[]) => boolean;
}

const Auth = createContext<Contexte | null>(null);

export function FournisseurAuth({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [chargement, setChargement] = useState(true);

  const appliquer = useCallback((s: Session | null) => {
    definirCsrf(s?.csrf_token ?? "");
    setSession(s);
  }, []);

  const actualiser = useCallback(async () => {
    try {
      appliquer(await appeler<Session>("GET", "/api/auth/moi", undefined, { garderSession: true }));
    } catch {
      appliquer(null);
    }
  }, [appliquer]);

  useEffect(() => {
    ecouterSessionPerdue(() => appliquer(null));
    actualiser().finally(() => setChargement(false));
  }, [actualiser, appliquer]);

  const connecter: Contexte["connecter"] = async (identifiant, motDePasse, code) => {
    try {
      const s = await appeler<Session>(
        "POST",
        "/api/auth/connexion",
        { identifiant, mot_de_passe: motDePasse, ...(code ? { code } : {}) },
        { garderSession: true },
      );
      appliquer(s);
      return "ok";
    } catch (e) {
      if (e instanceof ErreurApi && e.corps?.code_requis === true) return "code_requis";
      throw e;
    }
  };

  const deconnecter = async () => {
    try {
      await appeler("POST", "/api/auth/deconnexion", {}, { garderSession: true });
    } finally {
      appliquer(null);
    }
  };

  const valeur = useMemo<Contexte>(() => {
    const droits = new Set(session?.permissions ?? []);
    return {
      session,
      chargement,
      connecter,
      deconnecter,
      actualiser,
      appliquer,
      peut: (p) => droits.has(p),
      peutUn: (...ps) => ps.some((p) => droits.has(p)),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, chargement]);

  return <Auth.Provider value={valeur}>{children}</Auth.Provider>;
}

export function useAuth(): Contexte {
  const contexte = useContext(Auth);
  if (!contexte) throw new Error("useAuth hors du fournisseur d'authentification");
  return contexte;
}
