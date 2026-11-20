import { Link } from "react-router-dom";
import { lire, requete, type S } from "../api";
import { useAuth } from "../auth";
import { ROLES, STATUTS_COMMANDE, STATUTS_MOUVEMENT, TYPES_MOUVEMENT } from "../libelles";
import { Badge, Carte, Chargement, Page, Tableau as Table, Vide, date, nombre, useAnnuaire, useDonnees } from "../ui";

function Indicateur({ valeur, legende, vers, ton }: { valeur: number; legende: string; vers: string; ton?: string }) {
  return (
    <Link to={vers} style={{ color: "inherit", textDecoration: "none" }}>
      <Carte className="indicateur">
        <span className="valeur" style={ton ? { color: `var(--${ton})` } : undefined}>
          {nombre(valeur)}
        </span>
        <span className="legende">{legende}</span>
      </Carte>
    </Link>
  );
}

export function Tableau() {
  const { session, peut, peutUn } = useAuth();
  const nom = useAnnuaire();
  const utilisateur = session!.utilisateur;
  const voitAchats = peut("achats.consulter");
  const voitStock = peut("stock.consulter");
  const valideAchats = peut("achats.valider");
  const valideStock = peutUn("stock.valider_ajustement", "stock.valider_sortie_exceptionnelle", "stock.valider_entree_directe");

  const { donnees, erreur, chargement } = useDonnees(async () => {
    const [aValider, attendues, aControler, soldes, enAttente] = await Promise.all([
      valideAchats ? lire<S["CommandePublic"][]>("/api/commandes-achat" + requete({ statut: "soumise" })) : [],
      voitAchats
        ? lire<S["CommandePublic"][]>("/api/commandes-achat" + requete({ en_attente_marchandise: true }))
        : [],
      voitAchats ? lire<S["ReceptionPublic"][]>("/api/receptions-achat" + requete({ statut: "en_controle" })) : [],
      voitStock ? lire<S["SoldeArticle"][]>("/api/stock/soldes") : [],
      voitStock && valideStock
        ? lire<S["MouvementPublic"][]>("/api/stock/mouvements" + requete({ statut: "en_attente" }))
        : [],
    ]);
    return { aValider, attendues, aControler, soldes, enAttente };
  });

  return (
    <Page
      titre={`Bonjour ${utilisateur.nom.split(" ")[0]}`}
      sousTitre={`${ROLES[utilisateur.role] ?? utilisateur.role} — voici ce qui demande votre attention.`}
    >
      <Chargement erreur={erreur} chargement={chargement}>
        {donnees && (
          <>
            <div className="grille quatre">
              {valideAchats && (
                <Indicateur valeur={donnees.aValider.length} legende="Commandes à valider" vers="/commandes?statut=soumise" ton={donnees.aValider.length ? "alerte" : undefined} />
              )}
              {voitAchats && <Indicateur valeur={donnees.aControler.length} legende="Arrivées à contrôler" vers="/receptions" ton={donnees.aControler.length ? "alerte" : undefined} />}
              {voitAchats && <Indicateur valeur={donnees.attendues.length} legende="Commandes en attente de marchandise" vers="/commandes?attente=1" />}
              {valideStock && <Indicateur valeur={donnees.enAttente.length} legende="Mouvements à valider" vers="/stock/mouvements?statut=en_attente" ton={donnees.enAttente.length ? "alerte" : undefined} />}
              {voitStock && (
                <Indicateur
                  valeur={donnees.soldes.filter((s) => s.sous_seuil_min || s.negatif).length}
                  legende="Articles sous le seuil ou en négatif"
                  vers="/stock"
                  ton={donnees.soldes.some((s) => s.sous_seuil_min || s.negatif) ? "danger" : undefined}
                />
              )}
            </div>

            <div className="grille deux">
              {valideAchats && (
                <Carte titre="Commandes en attente de votre validation">
                  {donnees.aValider.length === 0 ? (
                    <Vide>Aucune commande à valider.</Vide>
                  ) : (
                    <Table colonnes={["Commande", "Prévue", "Saisie par"]}>
                      {donnees.aValider.map((c) => (
                        <tr key={c.id}>
                          <td>
                            <Link to={`/commandes/${c.id}`}>{c.numero}</Link>
                          </td>
                          <td>{date(c.date_arrivee_prevue)}</td>
                          <td>{nom(c.cree_par)}</td>
                        </tr>
                      ))}
                    </Table>
                  )}
                </Carte>
              )}

              {voitAchats && (
                <Carte titre="Marchandise attendue" droite={<Link to="/commandes?attente=1">Tout voir</Link>}>
                  {donnees.attendues.length === 0 ? (
                    <Vide>Aucune commande en attente de livraison.</Vide>
                  ) : (
                    <Table colonnes={["Commande", "Arrivée prévue", "État"]}>
                      {donnees.attendues.slice(0, 6).map((c) => (
                        <tr key={c.id}>
                          <td>
                            <Link to={`/commandes/${c.id}`}>{c.numero}</Link>
                          </td>
                          <td>{date(c.date_arrivee_prevue)}</td>
                          <td>
                            <Badge ton={STATUTS_COMMANDE[c.statut]?.ton}>{STATUTS_COMMANDE[c.statut]?.libelle}</Badge>
                          </td>
                        </tr>
                      ))}
                    </Table>
                  )}
                </Carte>
              )}

              {voitAchats && donnees.aControler.length > 0 && (
                <Carte titre="Arrivées à contrôler avant l'entrée en stock">
                  <Table colonnes={["Réception", "Conteneur", "Arrivée"]}>
                    {donnees.aControler.map((r) => (
                      <tr key={r.id}>
                        <td>
                          <Link to={`/receptions/${r.id}`}>{r.numero}</Link>
                        </td>
                        <td>{r.conteneur_reference ?? "—"}</td>
                        <td>{date(r.date_arrivee)}</td>
                      </tr>
                    ))}
                  </Table>
                </Carte>
              )}

              {valideStock && donnees.enAttente.length > 0 && (
                <Carte titre="Mouvements de stock à valider">
                  <Table colonnes={["Type", "Motif", "État"]}>
                    {donnees.enAttente.slice(0, 6).map((m) => (
                      <tr key={m.id}>
                        <td>{TYPES_MOUVEMENT[m.type]}</td>
                        <td>{m.motif}</td>
                        <td>
                          <Badge ton={STATUTS_MOUVEMENT[m.statut]?.ton}>{STATUTS_MOUVEMENT[m.statut]?.libelle}</Badge>
                        </td>
                      </tr>
                    ))}
                  </Table>
                </Carte>
              )}

              {voitStock && (
                <Carte titre="Stock à surveiller" droite={<Link to="/stock">Voir le stock</Link>}>
                  {donnees.soldes.filter((s) => s.sous_seuil_min || s.negatif).length === 0 ? (
                    <Vide>Aucun article sous son seuil.</Vide>
                  ) : (
                    <Table colonnes={["Article", { texte: "Disponible", droite: true }, "Alerte"]}>
                      {donnees.soldes
                        .filter((s) => s.sous_seuil_min || s.negatif)
                        .map((s) => (
                          <tr key={s.article_id}>
                            <td>{s.nom}</td>
                            <td className="droite">
                              {nombre(s.disponible, 1)} {s.unite}
                            </td>
                            <td>
                              <Badge ton="danger">{s.negatif ? "Stock négatif" : "Sous le seuil"}</Badge>
                            </td>
                          </tr>
                        ))}
                    </Table>
                  )}
                </Carte>
              )}
            </div>
          </>
        )}
      </Chargement>
    </Page>
  );
}
