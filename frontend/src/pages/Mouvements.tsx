import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { envoyer, lire, requete, type S } from "../api";
import { useAuth } from "../auth";
import { STATUTS_MOUVEMENT, TYPES_MOUVEMENT } from "../libelles";
import {
  Alerte,
  Badge,
  Bouton,
  Carte,
  Champ,
  Chargement,
  Choix,
  DemandeMotif,
  Page,
  Saisie,
  Tableau,
  Vide,
  dateHeure,
  messageErreur,
  nombre,
  useAnnuaire,
  useDonnees,
} from "../ui";

const DROIT_VALIDATION: Record<string, string> = {
  entree_directe: "stock.valider_entree_directe",
  ajustement: "stock.valider_ajustement",
  inventaire: "stock.valider_ajustement",
  sortie_exceptionnelle: "stock.valider_sortie_exceptionnelle",
  rebut_destruction: "stock.valider_sortie_exceptionnelle",
};

const TYPES_SAISISSABLES = ["entree_directe", "ajustement", "sortie_exceptionnelle", "rebut_destruction"];

function NouveauMouvement({ articles, onFermer, onCree }: {
  articles: S["ArticlePublic"][];
  onFermer: () => void;
  onCree: () => void;
}) {
  const [type, setType] = useState("ajustement");
  const [article, setArticle] = useState("");
  const [quantite, setQuantite] = useState("");
  const [sens, setSens] = useState<"plus" | "moins">("plus");
  const [motif, setMotif] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const choisissables = articles.filter((a) => (type === "entree_directe" ? a.niveau_stock === "produit_fini" : true));

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      await envoyer("/api/stock/mouvements", {
        type,
        article_id: article,
        quantite: quantite.replace(",", "."),
        motif,
        ...(type === "ajustement" ? { sens } : {}),
      });
      onCree();
    } catch (err) {
      setErreur(messageErreur(err));
      setEnvoi(false);
    }
  }

  return (
    <div className="voile" role="dialog" aria-modal="true">
      <form className="modale" onSubmit={soumettre}>
        <h2>Nouveau mouvement de stock</h2>
        <p className="soustitre" style={{ margin: 0 }}>
          Ce mouvement ne comptera dans le stock qu'une fois validé par une autre personne.
        </p>
        <Champ etiquette="Type">
          <Choix value={type} onChange={(e) => { setType(e.target.value); setArticle(""); }}>
            {TYPES_SAISISSABLES.map((t) => (
              <option key={t} value={t}>
                {TYPES_MOUVEMENT[t]}
              </option>
            ))}
          </Choix>
        </Champ>
        <Champ etiquette="Article" aide={type === "entree_directe" ? "Une entrée directe ne concerne que des produits finis (cartons déjà présents)." : undefined}>
          <Choix value={article} onChange={(e) => setArticle(e.target.value)}>
            <option value="">— Choisir —</option>
            {choisissables.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} — {a.nom}
              </option>
            ))}
          </Choix>
        </Champ>
        <div className="rangee">
          {type === "ajustement" && (
            <Champ etiquette="Sens">
              <Choix value={sens} onChange={(e) => setSens(e.target.value as "plus" | "moins")}>
                <option value="plus">Ajouter au stock</option>
                <option value="moins">Retirer du stock</option>
              </Choix>
            </Champ>
          )}
          <Champ etiquette="Quantité">
            <Saisie inputMode="decimal" value={quantite} onChange={(e) => setQuantite(e.target.value)} />
          </Champ>
        </div>
        <Champ etiquette="Motif" aide="Obligatoire : expliquez l'écart ou la raison de la sortie.">
          <textarea className="saisie" rows={2} value={motif} onChange={(e) => setMotif(e.target.value)} />
        </Champ>
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="actions droite">
          <Bouton type="button" variante="secondaire" onClick={onFermer}>
            Annuler
          </Bouton>
          <Bouton type="submit" chargement={envoi} disabled={!article || Number(quantite.replace(",", ".")) <= 0 || motif.trim().length < 5}>
            Enregistrer
          </Bouton>
        </div>
      </form>
    </div>
  );
}

export function Mouvements() {
  const { peut } = useAuth();
  const nom = useAnnuaire();
  const [params, setParams] = useSearchParams();
  const statut = params.get("statut") ?? "";
  const [creation, setCreation] = useState(false);
  const [rejet, setRejet] = useState<S["MouvementPublic"] | null>(null);
  const [probleme, setProbleme] = useState<string | null>(null);
  const { session } = useAuth();

  const { donnees, erreur, chargement, recharger } = useDonnees(async () => {
    const [mouvements, articles] = await Promise.all([
      lire<S["MouvementPublic"][]>("/api/stock/mouvements" + requete({ statut, limite: 100 })),
      lire<S["ArticlePublic"][]>("/api/articles"),
    ]);
    return { mouvements, articles };
  }, [statut]);

  const article = (id: string) => donnees?.articles.find((a) => a.id === id);

  async function valider(m: S["MouvementPublic"], decision: "valide" | "rejete", motif?: string) {
    setProbleme(null);
    try {
      await envoyer(`/api/stock/mouvements/${m.id}/validation`, { decision, motif });
      await recharger();
    } catch (e) {
      setProbleme(messageErreur(e));
      throw e;
    }
  }

  return (
    <Page
      titre="Mouvements de stock"
      sousTitre="Registre de tout ce qui entre et sort. Un mouvement ne se modifie jamais : une erreur se corrige par un mouvement inverse."
      actions={peut("stock.saisir") && <Bouton onClick={() => setCreation(true)}>Nouveau mouvement</Bouton>}
    >
      {probleme && <Alerte>{probleme}</Alerte>}
      <Carte>
        <div className="actions" style={{ marginBottom: 12 }}>
          <Choix aria-label="Filtrer" style={{ width: 260 }} value={statut} onChange={(e) => setParams(e.target.value ? { statut: e.target.value } : {})}>
            <option value="">Tous les mouvements</option>
            {Object.entries(STATUTS_MOUVEMENT).map(([cle, { libelle }]) => (
              <option key={cle} value={cle}>
                {libelle}
              </option>
            ))}
          </Choix>
        </div>
        <Chargement erreur={erreur} chargement={chargement}>
          {donnees && donnees.mouvements.length === 0 ? (
            <Vide>Aucun mouvement.</Vide>
          ) : (
            <Tableau colonnes={["Date", "Type", "Article", { texte: "Quantité", droite: true }, "Motif", "Saisi par", "État", ""]}>
              {donnees?.mouvements.map((m) => {
                const a = article(m.article_id);
                const droit = DROIT_VALIDATION[m.type];
                const peutDecider = m.statut === "en_attente" && droit && peut(droit) && m.cree_par !== session!.utilisateur.id;
                return (
                  <tr key={m.id}>
                    <td>{dateHeure(m.cree_le)}</td>
                    <td>{TYPES_MOUVEMENT[m.type]}</td>
                    <td>{a ? `${a.code}` : "—"}</td>
                    <td className="droite mono" style={{ color: m.quantite < 0 ? "var(--danger)" : undefined }}>
                      {m.quantite > 0 ? "+" : ""}
                      {nombre(m.quantite, 1)} {m.unite}
                    </td>
                    <td style={{ maxWidth: 280 }}>{m.motif}</td>
                    <td>{nom(m.cree_par)}</td>
                    <td>
                      <Badge ton={STATUTS_MOUVEMENT[m.statut]?.ton}>{STATUTS_MOUVEMENT[m.statut]?.libelle}</Badge>
                      {m.valide_par && <div className="champ-aide">par {nom(m.valide_par)}</div>}
                    </td>
                    <td className="actions">
                      {peutDecider && (
                        <>
                          <Bouton variante="primaire" onClick={() => valider(m, "valide").catch(() => undefined)}>
                            Valider
                          </Bouton>
                          <Bouton variante="secondaire" onClick={() => setRejet(m)}>
                            Rejeter
                          </Bouton>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </Tableau>
          )}
        </Chargement>
      </Carte>

      {creation && donnees && (
        <NouveauMouvement
          articles={donnees.articles.filter((a) => a.actif)}
          onFermer={() => setCreation(false)}
          onCree={() => {
            setCreation(false);
            recharger();
          }}
        />
      )}
      {rejet && (
        <DemandeMotif
          titre="Rejeter ce mouvement"
          consigne="Il ne comptera pas dans le stock. Le motif est conservé."
          libelleAction="Rejeter"
          onFermer={() => setRejet(null)}
          onConfirmer={async (motif) => {
            await valider(rejet, "rejete", motif);
            setRejet(null);
          }}
        />
      )}
    </Page>
  );
}
