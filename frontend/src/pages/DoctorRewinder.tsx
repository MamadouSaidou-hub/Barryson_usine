import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { lire, type S } from "../api";
import { STATUTS_ENCOURS } from "../libelles";
import { Badge, Carte, Chargement, Page, Tableau, Vide, date, nombre, useDonnees } from "../ui";

type Filtre = "en_cours" | "a_valider" | "traite" | "tous";

const FILTRES: { cle: Filtre; titre: string; aide: string }[] = [
  { cle: "en_cours", titre: "À traiter", aide: "pièces parties, retour à déclarer" },
  { cle: "a_valider", titre: "À valider", aide: "traitement déclaré, en attente du DG" },
  { cle: "traite", titre: "Traités", aide: "validés, pièces récupérées en stock" },
  { cle: "tous", titre: "Tous", aide: "depuis le début" },
];

export function DoctorRewinder() {
  const aller = useNavigate();
  const [params, setParams] = useSearchParams();
  const filtre = (params.get("statut") as Filtre | null) ?? "en_cours";

  const { donnees, erreur, chargement } = useDonnees(async () => {
    const [encours, indicateurs, ordres, modeles] = await Promise.all([
      lire<S["EncoursPublic"][]>("/api/doctor-rewinder"),
      lire<S["Indicateurs"]>("/api/doctor-rewinder/indicateurs"),
      lire<S["OrdrePublic"][]>("/api/ordres-fabrication").catch(() => [] as S["OrdrePublic"][]),
      lire<S["ModelePublic"][]>("/api/modeles-ruban").catch(() => [] as S["ModelePublic"][]),
    ]);
    return {
      encours,
      indicateurs,
      ordres: Object.fromEntries(ordres.map((o) => [o.id, o.numero])),
      modeles: Object.fromEntries(modeles.map((m) => [m.id, m.code])),
    };
  });

  const compte = (cle: Filtre) =>
    !donnees ? 0 : cle === "tous" ? donnees.encours.length : donnees.encours.filter((e) => e.statut === cle).length;
  const liste = !donnees ? [] : filtre === "tous" ? donnees.encours : donnees.encours.filter((e) => e.statut === filtre);
  const i = donnees?.indicateurs;

  return (
    <Page
      titre="Doctor Rewinder"
      sousTitre="Pièces envoyées à rectifier : ni perdues, ni encore en stock. Seules les pièces récupérées et validées entrent en stock."
    >
      <Chargement erreur={erreur} chargement={chargement}>
        {donnees && i && (
          <>
            <div className="grille quatre">
              {FILTRES.map((f) => (
                <button
                  key={f.cle}
                  type="button"
                  className={`carte indicateur filtre${filtre === f.cle ? " actif" : ""}`}
                  onClick={() => setParams({ statut: f.cle })}
                  aria-pressed={filtre === f.cle}
                >
                  <span className="legende">{f.titre}</span>
                  <span className="valeur">{nombre(compte(f.cle))}</span>
                  <span className="legende">{f.aide}</span>
                </button>
              ))}
            </div>

            <Carte titre="Indicateurs">
              <dl className="definition">
                <dt>Pièces en cours de rectification</dt>
                <dd>
                  {nombre(i.pieces_en_cours)} pièces dans {nombre(i.encours_ouverts)} dossier(s)
                </dd>
                <dt>Taux de récupération</dt>
                <dd>
                  {i.taux_recuperation === null
                    ? "— (aucun dossier validé)"
                    : `${nombre(Number(i.taux_recuperation) * 100, 1)} % (${nombre(i.pieces_recuperees)} récupérées sur ${nombre(i.pieces_envoyees_traitees)} envoyées)`}
                </dd>
                <dt>Délai moyen de traitement</dt>
                <dd>{i.delai_moyen_jours === null ? "—" : `${nombre(i.delai_moyen_jours, 1)} jour(s)`}</dd>
                <dt>Plus ancien encours</dt>
                <dd>
                  {i.anciennete_max_jours === null || i.plus_ancien_id === null ? (
                    "—"
                  ) : (
                    <Link to={`/doctor-rewinder/${i.plus_ancien_id}`}>{nombre(i.anciennete_max_jours)} jour(s)</Link>
                  )}
                </dd>
              </dl>
            </Carte>

            <Carte titre={`${FILTRES.find((f) => f.cle === filtre)?.titre ?? "Dossiers"} (${liste.length})`}>
              {liste.length === 0 ? (
                <Vide>
                  {filtre === "en_cours"
                    ? "Aucune pièce chez le Doctor Rewinder. Un dossier s'ouvre à la clôture d'un ordre de fabrication qui y a envoyé des pièces."
                    : "Aucun dossier dans cette catégorie."}
                </Vide>
              ) : (
                <Tableau colonnes={["Ordre", "Modèle", "Envoyées", "Envoi", "Récupérées", "Perdues", "État"]}>
                  {liste.map((e) => (
                    <tr key={e.id} className="cliquable" onClick={() => aller(`/doctor-rewinder/${e.id}`)}>
                      <td className="mono">{donnees.ordres[e.ordre_id] ?? "—"}</td>
                      <td>{donnees.modeles[e.modele_id] ?? "—"}</td>
                      <td>{nombre(e.quantite_envoyee)}</td>
                      <td>{date(e.date_envoi)}</td>
                      <td>{e.quantite_recuperee === null ? "—" : nombre(e.quantite_recuperee)}</td>
                      <td>{e.quantite_non_recuperable === null ? "—" : nombre(e.quantite_non_recuperable)}</td>
                      <td>
                        <Badge ton={STATUTS_ENCOURS[e.statut]?.ton}>{STATUTS_ENCOURS[e.statut]?.libelle}</Badge>
                      </td>
                    </tr>
                  ))}
                </Tableau>
              )}
            </Carte>
          </>
        )}
      </Chargement>
    </Page>
  );
}
