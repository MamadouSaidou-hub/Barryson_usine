import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useState } from "react";
import { lire, requete, type S } from "../api";
import { useAuth } from "../auth";
import { STATUTS_COMMANDE, STATUTS_RECEPTION } from "../libelles";
import { Badge, Bouton, Carte, Chargement, Page, Saisie, Tableau, Vide, date, dateHeure, nombre, useAnnuaire, useDonnees } from "../ui";

type Filtre = "en_controle" | "litiges" | "acceptee" | "toutes";

const FILTRES: { cle: Filtre; titre: string; aide: string }[] = [
  { cle: "en_controle", titre: "À contrôler", aide: "arrivées en attente de contrôle" },
  { cle: "litiges", titre: "Litiges", aide: "réserves ou refus à traiter" },
  { cle: "acceptee", titre: "Acceptées", aide: "entrées en stock" },
  { cle: "toutes", titre: "Toutes", aide: "depuis le début" },
];

const aujourdhui = () => new Date().toISOString().slice(0, 10);

export function Receptions() {
  const aller = useNavigate();
  const nom = useAnnuaire();
  const { peut } = useAuth();
  const [params, setParams] = useSearchParams();
  const filtre = (params.get("statut") as Filtre | null) ?? "en_controle";
  const [recherche, setRecherche] = useState("");

  const { donnees, erreur, chargement } = useDonnees(async () => {
    const [receptions, litiges, fournisseurs, commandes] = await Promise.all([
      lire<S["ReceptionPublic"][]>("/api/receptions-achat"),
      lire<S["ReceptionPublic"][]>("/api/receptions-achat" + requete({ avec_ecarts: true })),
      lire<S["FournisseurPublic"][]>("/api/fournisseurs"),
      lire<S["CommandePublic"][]>("/api/commandes-achat"),
    ]);
    return {
      receptions,
      litiges,
      attendues: commandes.filter((c) => c.statut === "commandee" || c.statut === "partiellement_recue"),
      fournisseurs: Object.fromEntries(fournisseurs.map((f) => [f.id, f.nom])),
      commandes: Object.fromEntries(commandes.map((c) => [c.id, c])),
    };
  });

  const compte = (cle: Filtre) =>
    !donnees
      ? 0
      : cle === "litiges"
        ? donnees.litiges.length
        : cle === "toutes"
          ? donnees.receptions.length
          : donnees.receptions.filter((r) => r.statut === cle).length;

  const base = !donnees
    ? []
    : filtre === "litiges"
      ? donnees.litiges
      : filtre === "toutes"
        ? donnees.receptions
        : donnees.receptions.filter((r) => r.statut === filtre);
  const terme = recherche.trim().toLowerCase();
  const liste = base.filter(
    (r) =>
      !terme ||
      [r.numero, r.conteneur_reference, r.numero_facture, donnees?.commandes[r.commande_id]?.numero]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(terme)),
  );

  return (
    <Page
      titre="Arrivées de marchandise"
      sousTitre="Chaque arrivée est contrôlée avant d'entrer en stock : seules les quantités acceptées sont enregistrées."
    >
      <Chargement erreur={erreur} chargement={chargement}>
        {donnees && (
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

            <Carte
              titre={`Marchandise attendue (${donnees.attendues.length})`}
              droite={peut("achats.consulter") && <Link to="/commandes?attente=1">Voir dans les commandes</Link>}
            >
              {donnees.attendues.length === 0 ? (
                <Vide>
                  Aucune commande en attente de marchandise. Une arrivée se déclare à partir d'une commande passée au fournisseur :
                  ouvrez-la depuis <Link to="/commandes">Commandes d'achat</Link>.
                </Vide>
              ) : (
                <Tableau colonnes={["Commande", "Fournisseur", "État", "Arrivée prévue", ""]}>
                  {donnees.attendues.map((c) => {
                    const retard = c.date_arrivee_prevue !== null && c.date_arrivee_prevue < aujourdhui();
                    return (
                      <tr key={c.id}>
                        <td className="mono">
                          <Link to={`/commandes/${c.id}`}>{c.numero}</Link>
                        </td>
                        <td>{donnees.fournisseurs[c.fournisseur_id] ?? "—"}</td>
                        <td>
                          <Badge ton={STATUTS_COMMANDE[c.statut]?.ton}>{STATUTS_COMMANDE[c.statut]?.libelle}</Badge>
                        </td>
                        <td>
                          {date(c.date_arrivee_prevue)}
                          {retard && <> <Badge ton="danger">En retard</Badge></>}
                        </td>
                        <td className="droite">
                          {peut("stock.saisir") && (
                            <Bouton variante="secondaire" onClick={() => aller(`/commandes/${c.id}/arrivee`)}>
                              Enregistrer l'arrivée
                            </Bouton>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </Tableau>
              )}
            </Carte>

            <Carte titre={`${FILTRES.find((f) => f.cle === filtre)?.titre ?? "Arrivées"} (${liste.length})`}>
              <div className="actions" style={{ marginBottom: 12 }}>
                <Saisie
                  aria-label="Rechercher une arrivée"
                  placeholder="Rechercher : n° de réception, conteneur, facture, commande…"
                  style={{ maxWidth: 480 }}
                  value={recherche}
                  onChange={(e) => setRecherche(e.target.value)}
                />
              </div>
              {liste.length === 0 ? (
                <Vide>
                  {terme
                    ? "Aucune arrivée ne correspond à cette recherche."
                    : filtre === "en_controle"
                      ? "Rien à contrôler pour le moment."
                      : "Aucune arrivée dans cette catégorie."}
                </Vide>
              ) : (
                <Tableau colonnes={["Réception", "Commande", "Conteneur", "Facture", "Arrivée", "État", "Contrôle", ""]}>
                  {liste.map((r) => {
                    const commande = donnees.commandes[r.commande_id];
                    return (
                      <tr key={r.id} className="cliquable" onClick={() => aller(`/receptions/${r.id}`)}>
                        <td className="mono">{r.numero}</td>
                        <td>
                          {commande ? <span className="mono">{commande.numero}</span> : "—"}
                          {commande && <div className="champ-aide">{donnees.fournisseurs[commande.fournisseur_id]}</div>}
                        </td>
                        <td>{r.conteneur_reference ?? "—"}</td>
                        <td>{r.numero_facture ?? "—"}</td>
                        <td>{date(r.date_arrivee)}</td>
                        <td>
                          <Badge ton={STATUTS_RECEPTION[r.statut]?.ton}>{STATUTS_RECEPTION[r.statut]?.libelle}</Badge>
                        </td>
                        <td>
                          {r.controle_par ? (
                            <>
                              {nom(r.controle_par)}
                              <div className="champ-aide">{dateHeure(r.controle_le)}</div>
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="droite">
                          {r.statut === "en_controle" && peut("stock.valider_reception") && (
                            <Bouton
                              onClick={(e) => {
                                e.stopPropagation();
                                aller(`/receptions/${r.id}`);
                              }}
                            >
                              Contrôler
                            </Bouton>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </Tableau>
              )}
            </Carte>
          </>
        )}
      </Chargement>
    </Page>
  );
}
