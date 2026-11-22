import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
  type SelectHTMLAttributes,
  type InputHTMLAttributes,
} from "react";
import { Link } from "react-router-dom";
import { ErreurApi, lire, type S } from "./api";
import type { Ton } from "./libelles";

// --- Formats ---------------------------------------------------------------------------------

export const nombre = (v: number | null | undefined, decimales = 0) =>
  v === null || v === undefined
    ? "—"
    : new Intl.NumberFormat("fr-FR", { maximumFractionDigits: decimales }).format(v);

export const montant = (v: number | null | undefined, devise: string) =>
  v === null || v === undefined ? "—" : `${nombre(v, devise === "GNF" ? 0 : 2)} ${devise}`;

export const date = (v: string | null | undefined) =>
  v ? new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" }).format(new Date(v)) : "—";

export const dateHeure = (v: string | null | undefined) =>
  v ? new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" }).format(new Date(v)) : "—";

export const messageErreur = (e: unknown) =>
  e instanceof ErreurApi ? e.message : e instanceof Error ? e.message : "Erreur inattendue.";

// --- Chargement de donnees ------------------------------------------------------------------------

export function useDonnees<T>(chargeur: () => Promise<T>, dependances: unknown[] = []) {
  const [donnees, setDonnees] = useState<T | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [chargement, setChargement] = useState(true);
  const chargeurRef = useRef(chargeur);
  chargeurRef.current = chargeur;

  const recharger = useCallback(async () => {
    setChargement(true);
    try {
      setDonnees(await chargeurRef.current());
      setErreur(null);
    } catch (e) {
      setErreur(messageErreur(e));
    } finally {
      setChargement(false);
    }
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void recharger(), dependances);
  return { donnees, erreur, chargement, recharger };
}

type Annuaire = Record<string, S["EntreeAnnuaire"]>;
let annuaireEnCache: Promise<Annuaire> | null = null;

/** Noms des personnes (« validé par ... ») : un seul chargement pour toute l'application. */
export function useAnnuaire() {
  const [annuaire, setAnnuaire] = useState<Annuaire>({});
  useEffect(() => {
    annuaireEnCache ??= lire<S["EntreeAnnuaire"][]>("/api/annuaire").then((liste) =>
      Object.fromEntries(liste.map((u) => [u.id, u])),
    );
    annuaireEnCache.then(setAnnuaire).catch(() => (annuaireEnCache = null));
  }, []);
  return (id: string | null | undefined) => (id ? (annuaire[id]?.nom ?? "—") : "—");
}

export const oublierAnnuaire = () => {
  annuaireEnCache = null;
};

// --- Composants --------------------------------------------------------------------------------

export function Badge({ ton = "neutre", children }: { ton?: Ton; children: ReactNode }) {
  return <span className={`badge badge-${ton}`}>{children}</span>;
}

export function Page({ titre, sousTitre, actions, children }: {
  titre: string;
  sousTitre?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="page">
      <header className="page-entete">
        <div>
          <h1>{titre}</h1>
          {sousTitre && <p className="soustitre">{sousTitre}</p>}
        </div>
        {actions && <div className="actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

export function Carte({ titre, droite, children, className = "" }: {
  titre?: ReactNode;
  droite?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`carte ${className}`}>
      {(titre || droite) && (
        <div className="carte-entete">
          <h2>{titre}</h2>
          {droite}
        </div>
      )}
      {children}
    </div>
  );
}

export function Alerte({ ton = "danger", children }: { ton?: Ton; children: ReactNode }) {
  return (
    <div className={`alerte alerte-${ton}`} role={ton === "danger" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Chargement({ erreur, chargement, children }: {
  erreur: string | null;
  chargement: boolean;
  children: ReactNode;
}) {
  if (erreur) return <Alerte>{erreur}</Alerte>;
  if (chargement) return <p className="vide">Chargement…</p>;
  return <>{children}</>;
}

export function Vide({ children }: { children: ReactNode }) {
  return <p className="vide">{children}</p>;
}

export function Bouton({ variante = "primaire", chargement, children, ...props }: {
  variante?: "primaire" | "secondaire" | "danger" | "lien";
  chargement?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button className={`bouton bouton-${variante}`} disabled={chargement || props.disabled} {...props}>
      {chargement ? "…" : children}
    </button>
  );
}

export function Champ({ etiquette, aide, erreur, children }: {
  etiquette: string;
  aide?: ReactNode;
  erreur?: string;
  children: ReactNode;
}) {
  return (
    <label className="champ">
      <span className="champ-etiquette">{etiquette}</span>
      {children}
      {aide && <span className="champ-aide">{aide}</span>}
      {erreur && <span className="champ-erreur">{erreur}</span>}
    </label>
  );
}

export const Saisie = (props: InputHTMLAttributes<HTMLInputElement>) => <input className="saisie" {...props} />;
export const Choix = (props: SelectHTMLAttributes<HTMLSelectElement>) => (
  <select className="saisie" {...props} />
);

export function Tableau({ colonnes, children, className = "" }: {
  colonnes: (string | { texte: string; droite?: boolean })[];
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="tableau-conteneur">
      <table className={`tableau ${className}`}>
        <thead>
          <tr>
            {colonnes.map((c, i) => {
              const { texte, droite } = typeof c === "string" ? { texte: c, droite: false } : c;
              return (
                <th key={i} className={droite ? "droite" : ""}>
                  {texte}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export const Lien = Link;

/** Fenetre de confirmation avec saisie d'un motif (refus, annulation, rejet...). */
export function DemandeMotif({ titre, consigne, libelleAction, ton = "danger", minimum = 5, onConfirmer, onFermer }: {
  titre: string;
  consigne?: string;
  libelleAction: string;
  ton?: "primaire" | "danger";
  minimum?: number;
  onConfirmer: (motif: string) => Promise<void>;
  onFermer: () => void;
}) {
  const [motif, setMotif] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      await onConfirmer(motif.trim());
    } catch (err) {
      setErreur(messageErreur(err));
      setEnvoi(false);
    }
  }

  return (
    <div className="voile" role="dialog" aria-modal="true" aria-label={titre}>
      <form className="modale" onSubmit={soumettre}>
        <h2>{titre}</h2>
        {consigne && <p className="soustitre">{consigne}</p>}
        <Champ etiquette="Motif">
          <textarea className="saisie" rows={3} value={motif} autoFocus onChange={(e) => setMotif(e.target.value)} />
        </Champ>
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="actions droite">
          <Bouton type="button" variante="secondaire" onClick={onFermer}>
            Retour
          </Bouton>
          <Bouton type="submit" variante={ton} chargement={envoi} disabled={motif.trim().length < minimum}>
            {libelleAction}
          </Bouton>
        </div>
      </form>
    </div>
  );
}
