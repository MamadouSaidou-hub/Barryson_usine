import { useState } from "react";
import { lire, requete, type S } from "../api";
import { FINITIONS } from "../libelles";
import { Badge, Carte, Chargement, Page, Tableau, Vide, date, nombre, useDonnees } from "../ui";

const STATUTS_BOBINE: Record<string, { libelle: string; ton: "ok" | "alerte" | "neutre" }> = {
  disponible: { libelle: "Disponible", ton: "ok" },
  entamee_presente: { libelle: "Entamée, présente", ton: "alerte" },
  epuisee: { libelle: "Épuisée", ton: "neutre" },
};

export function Lots() {
  const [lotId, setLotId] = useState<string | null>(null);
  const lots = useDonnees(() => lire<S["LotPublic"][]>("/api/lots"));
  const bobines = useDonnees(
    () => (lotId ? lire<S["BobinePublic"][]>("/api/bobines" + requete({ lot_id: lotId })) : Promise.resolve([])),
    [lotId],
  );
  const lot = lots.donnees?.find((l) => l.id === lotId);

  return (
    <Page titre="Lots et bobines" sousTitre="Chaque conteneur reçu est un lot. Une bobine est identifiée par son lot et son numéro fournisseur.">
      <div className="grille deux">
        <Carte titre="Lots reçus">
          <Chargement erreur={lots.erreur} chargement={lots.chargement}>
            {lots.donnees && lots.donnees.length === 0 ? (
              <Vide>Aucun lot reçu pour le moment.</Vide>
            ) : (
              <Tableau colonnes={["Conteneur", "Reçu le", { texte: "Bobines", droite: true }]}>
                {lots.donnees?.map((l) => (
                  <tr key={l.id} className="cliquable" onClick={() => setLotId(l.id)} style={lotId === l.id ? { background: "var(--couleur-primaire-claire)" } : undefined}>
                    <td>
                      <strong>{l.conteneur_reference}</strong>
                      {l.numero_facture && <div className="champ-aide">Facture {l.numero_facture}</div>}
                    </td>
                    <td>{date(l.date_reception)}</td>
                    <td className="droite">{nombre(l.nb_bobines)}</td>
                  </tr>
                ))}
              </Tableau>
            )}
          </Chargement>
        </Carte>

        <Carte titre={lot ? `Bobines du conteneur ${lot.conteneur_reference}` : "Bobines"}>
          {!lotId ? (
            <Vide>Choisissez un lot pour voir ses bobines.</Vide>
          ) : (
            <Chargement erreur={bobines.erreur} chargement={bobines.chargement}>
              <Tableau colonnes={["N°", "Finition", { texte: "Poids (kg)", droite: true }, { texte: "Métrage (m)", droite: true }, "État"]}>
                {bobines.donnees?.slice(0, 300).map((b) => (
                  <tr key={b.id}>
                    <td className="mono">{b.numero_fournisseur}</td>
                    <td>{FINITIONS[b.couleur_finition]}</td>
                    <td className="droite">{nombre(b.poids_kg, 1)}</td>
                    <td className="droite">{b.metrage_propre === null ? <Badge ton="alerte">à renseigner</Badge> : nombre(b.metrage_propre)}</td>
                    <td>
                      <Badge ton={STATUTS_BOBINE[b.statut]?.ton}>{STATUTS_BOBINE[b.statut]?.libelle}</Badge>
                    </td>
                  </tr>
                ))}
              </Tableau>
              {(bobines.donnees?.length ?? 0) > 300 && <p className="champ-aide">300 premières bobines affichées sur {bobines.donnees?.length}.</p>}
            </Chargement>
          )}
        </Carte>
      </div>
    </Page>
  );
}
