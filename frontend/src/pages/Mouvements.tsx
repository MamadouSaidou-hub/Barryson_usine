import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { envoyer, lire, requete, type S } from "../api";
import { useAuth } from "../auth";
import { STATUTS_MOUVEMENT, TYPES_MOUVEMENT } from "../libelles";
import {
  Alerte,
  Badge,
  Bouton,
  Carte,
  Chargement,
  Choix,
  DemandeMotif,
  Page,
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

export function Mouvements() {
  const { peut } = useAuth();
  const nom = useAnnuaire();
  const [params, setParams] = useSearchParams();
  const statut = params.get("statut") ?? "";
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
      titre="Historique du stock"
      sousTitre="Tout ce qui est entré et sorti. Une écriture ne se modifie jamais : une erreur se corrige par l'écriture inverse."
      actions={<Link to="/stock">← Retour au stock</Link>}
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
