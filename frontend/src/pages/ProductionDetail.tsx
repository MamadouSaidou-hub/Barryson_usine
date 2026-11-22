import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { envoyer, lire, remplacer, type S } from "../api";
import { useAuth } from "../auth";
import { FINITIONS, STATUTS_OF } from "../libelles";
import {
  Alerte,
  Badge,
  Bouton,
  Carte,
  Champ,
  Chargement,
  DemandeMotif,
  Page,
  Saisie,
  dateHeure,
  messageErreur,
  nombre,
  useAnnuaire,
  useDonnees,
} from "../ui";

const CHAMPS = [
  { cle: "tours_totaux", etiquette: "Tours faits", aide: "Total des tours de la bobine, d'après le rapport de l'opérateur." },
  { cle: "tours_defectueux", etiquette: "Tours défectueux", aide: "Tours entiers jetés (chaque tour = plusieurs pièces)." },
  { cle: "pieces_defectueuses_supplementaires", etiquette: "Autres pièces défectueuses", aide: "Pièces isolées non conformes, hors tours défectueux." },
  { cle: "quantite_doctor_rewinder", etiquette: "Envoyées au Doctor Rewinder", aide: "Pièces à retravailler." },
  { cle: "pertes_definitives", etiquette: "Pertes définitives", aide: "Pièces détruites, sans reprise possible." },
] as const;

type Cle = (typeof CHAMPS)[number]["cle"];

function Resultat({ ordre, onEnregistre }: { ordre: S["OrdreDetail"]; onEnregistre: () => void }) {
  const [valeurs, setValeurs] = useState<Record<Cle, string>>(() =>
    Object.fromEntries(CHAMPS.map((c) => [c.cle, ordre[c.cle]?.toString() ?? ""])) as Record<Cle, string>,
  );
  const [epuisee, setEpuisee] = useState(ordre.bobine_epuisee ?? false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const complet = CHAMPS.every((c) => /^\d+$/.test(valeurs[c.cle].trim()));

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      await remplacer(`/api/ordres-fabrication/${ordre.id}/resultat`, {
        ...Object.fromEntries(CHAMPS.map((c) => [c.cle, Number(valeurs[c.cle])])),
        bobine_epuisee: epuisee,
      });
      onEnregistre();
    } catch (err) {
      setErreur(messageErreur(err));
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <Carte titre={ordre.statut === "resultat_saisi" ? "Corriger le résultat" : "Saisir le résultat de fabrication"}>
      <form className="formulaire" onSubmit={soumettre}>
        <p className="champ-aide" style={{ marginTop: 0 }}>
          Recopiez le rapport papier de l'opérateur. Prévu : {nombre(ordre.tours_prevus)} tours, {nombre(ordre.pieces_theoriques)} pièces.
        </p>
        <div className="rangee">
          {CHAMPS.map((c) => (
            <Champ key={c.cle} etiquette={c.etiquette} aide={c.aide}>
              <Saisie
                inputMode="numeric"
                value={valeurs[c.cle]}
                onChange={(e) => setValeurs({ ...valeurs, [c.cle]: e.target.value })}
              />
            </Champ>
          ))}
        </div>
        <label className="case">
          <input type="checkbox" checked={epuisee} onChange={(e) => setEpuisee(e.target.checked)} />
          <span>La bobine est entièrement consommée (elle sortira du stock à la clôture)</span>
        </label>
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="actions">
          <Bouton type="submit" chargement={envoi} disabled={!complet}>
            Enregistrer le résultat
          </Bouton>
        </div>
      </form>
    </Carte>
  );
}

export function ProductionDetail() {
  const { id } = useParams();
  const { peut } = useAuth();
  const nom = useAnnuaire();
  const [annulation, setAnnulation] = useState(false);
  const [derogation, setDerogation] = useState(false);
  const [probleme, setProbleme] = useState<string | null>(null);
  const [enCours, setEnCours] = useState<string | null>(null);

  const { donnees, erreur, chargement, recharger } = useDonnees(async () => {
    const ordre = await lire<S["OrdreDetail"]>(`/api/ordres-fabrication/${id}`);
    const [modeles, bobines] = await Promise.all([
      lire<S["ModelePublic"][]>("/api/modeles-ruban"),
      lire<S["BobinePublic"][]>(`/api/bobines`),
    ]);
    // Le dossier Doctor Rewinder n'existe qu'une fois l'ordre clôturé, et seuls certains profils le voient.
    const encours =
      ordre.statut === "cloture"
        ? await lire<S["EncoursPublic"][]>(`/api/doctor-rewinder?ordre_id=${ordre.id}`).catch(() => [])
        : [];
    return {
      ordre,
      modele: modeles.find((m) => m.id === ordre.modele_id),
      bobine: bobines.find((b) => b.id === ordre.bobine_id),
      encours: encours[0],
    };
  }, [id]);

  async function etape(chemin: string) {
    setEnCours(chemin);
    setProbleme(null);
    try {
      await envoyer(`/api/ordres-fabrication/${id}/${chemin}`);
      await recharger();
    } catch (e) {
      setProbleme(messageErreur(e));
    } finally {
      setEnCours(null);
    }
  }

  const o = donnees?.ordre;
  const statut = o?.statut ?? "";
  const r = o?.resultat;

  return (
    <Page
      titre={o ? `Ordre ${o.numero}` : "Ordre de fabrication"}
      sousTitre={donnees?.modele ? `${donnees.modele.code} — ${donnees.modele.nom}` : undefined}
      actions={
        o && (
          <>
            <Badge ton={STATUTS_OF[statut]?.ton}>{STATUTS_OF[statut]?.libelle}</Badge>
            <Link to="/production">← Tous les ordres</Link>
          </>
        )
      }
    >
      <Chargement erreur={erreur} chargement={chargement}>
        {o && donnees && (
          <>
            {probleme && <Alerte>{probleme}</Alerte>}
            {o.alertes.map((a) => (
              <Alerte key={a.code} ton="alerte">
                {a.message}
              </Alerte>
            ))}

            <div className="actions">
              {statut === "brouillon" && peut("production.saisir") && (
                <Bouton onClick={() => etape("soumettre")} chargement={enCours === "soumettre"}>
                  Soumettre (réserve les tubes)
                </Bouton>
              )}
              {statut === "soumis" && peut("stock.executer_sortie") && (
                <Bouton onClick={() => etape("valider-matieres")} chargement={enCours === "valider-matieres"}>
                  Sortir les tubes du stock
                </Bouton>
              )}
              {statut === "soumis" && peut("stock.valider_sortie_exceptionnelle") && o.alertes.some((a) => a.code === "tubes_insuffisants") && (
                <Bouton variante="secondaire" onClick={() => setDerogation(true)}>
                  Accorder une dérogation (tubes manquants)
                </Bouton>
              )}
              {statut === "matieres_validees" && peut("production.saisir") && (
                <Bouton onClick={() => etape("demarrer")} chargement={enCours === "demarrer"}>
                  Démarrer la fabrication
                </Bouton>
              )}
              {statut === "resultat_saisi" && peut("production.valider") && (
                <Bouton onClick={() => etape("valider-resultat")} chargement={enCours === "valider-resultat"}>
                  Valider le résultat
                </Bouton>
              )}
              {statut === "resultat_valide" && peut("production.cloturer") && (
                <Bouton onClick={() => etape("cloturer")} chargement={enCours === "cloturer"}>
                  Clôturer (entrée des produits finis en stock)
                </Bouton>
              )}
              {!["cloture", "annule"].includes(statut) && peut("production.annuler") && (
                <Bouton variante="secondaire" onClick={() => setAnnulation(true)}>
                  Annuler l'ordre
                </Bouton>
              )}
            </div>

            <div className="grille deux">
              <Carte titre="Fabrication">
                <dl className="definition">
                  <dt>Bobine</dt>
                  <dd>
                    {donnees.bobine ? (
                      <>
                        {donnees.bobine.numero_fournisseur} · {FINITIONS[donnees.bobine.couleur_finition]}
                      </>
                    ) : (
                      "—"
                    )}
                  </dd>
                  <dt>Métrage engagé</dt>
                  <dd>{nombre(o.metrage_engage, 0)} m</dd>
                  <dt>Préparé par</dt>
                  <dd>
                    {nom(o.cree_par)} le {dateHeure(o.cree_le)}
                  </dd>
                  {o.commentaire && (
                    <>
                      <dt>Commentaire</dt>
                      <dd>{o.commentaire}</dd>
                    </>
                  )}
                  {o.motif_annulation && (
                    <>
                      <dt>Motif d'annulation</dt>
                      <dd>{o.motif_annulation}</dd>
                    </>
                  )}
                </dl>
              </Carte>

              <Carte titre="Prévision">
                {o.pieces_theoriques === null ? (
                  <p className="champ-aide">Calculée à la soumission de l'ordre.</p>
                ) : (
                  <dl className="definition">
                    <dt>Tours</dt>
                    <dd>{nombre(o.tours_prevus)}</dd>
                    <dt>Pièces théoriques</dt>
                    <dd>{nombre(o.pieces_theoriques)}</dd>
                    <dt>Cartons</dt>
                    <dd>{nombre(o.cartons_prevus)}</dd>
                    <dt>Pièces hors carton</dt>
                    <dd>{nombre(o.pieces_restantes_prevues)}</dd>
                  </dl>
                )}
              </Carte>
            </div>

            {(statut === "en_cours" || statut === "resultat_saisi") && peut("production.saisir") && (
              <Resultat key={o.resultat_saisi_le ?? "nouveau"} ordre={o} onEnregistre={recharger} />
            )}

            {r && (
              <Carte
                titre="Résultat"
                droite={
                  r.coherent ? <Badge ton="ok">Comptage cohérent</Badge> : <Badge ton="danger">Comptage incohérent</Badge>
                }
              >
                {!r.coherent && (
                  <Alerte>
                    {r.ecart_comptage > 0
                      ? `${r.ecart_comptage} pièce(s) non conforme(s) ne sont ni au Doctor Rewinder ni perdues : une pièce a été oubliée.`
                      : `${-r.ecart_comptage} pièce(s) comptée(s) deux fois entre le Doctor Rewinder et les pertes.`}{" "}
                    Corrigez la saisie avant de valider.
                  </Alerte>
                )}
                <dl className="definition">
                  <dt>Pièces brutes</dt>
                  <dd>{nombre(r.pieces_brutes)}</dd>
                  <dt>Non conformes</dt>
                  <dd>{nombre(r.pieces_non_conformes)}</dd>
                  <dt>Conformes</dt>
                  <dd>
                    <strong>{nombre(r.pieces_conformes)}</strong>
                  </dd>
                  <dt>Cartons complets</dt>
                  <dd>
                    {nombre(r.cartons_complets)} (+ {nombre(r.pieces_restantes)} pièces hors carton)
                  </dd>
                  <dt>Écart avec la prévision</dt>
                  <dd>
                    {r.ecart_pieces > 0 ? "+" : ""}
                    {nombre(r.ecart_pieces)} pièces ({nombre(r.ecart_pourcentage, 1)} %)
                  </dd>
                  <dt>Rendement</dt>
                  <dd>{nombre(Number(r.rendement) * 100, 1)} %</dd>
                  <dt>Bobine</dt>
                  <dd>{o.bobine_epuisee ? "Épuisée" : "Entamée, reste présente"}</dd>
                  {donnees.encours && (
                    <>
                      <dt>Doctor Rewinder</dt>
                      <dd>
                        <Link to={`/doctor-rewinder/${donnees.encours.id}`}>
                          {nombre(donnees.encours.quantite_envoyee)} pièces — voir le dossier
                        </Link>
                      </dd>
                    </>
                  )}
                  {o.resultat_saisi_par && (
                    <>
                      <dt>Saisi par</dt>
                      <dd>
                        {nom(o.resultat_saisi_par)} le {dateHeure(o.resultat_saisi_le)}
                      </dd>
                    </>
                  )}
                </dl>
              </Carte>
            )}

            <Carte titre="Historique">
              <ul className="historique">
                {o.transitions.map((t, i) => (
                  <li key={i}>
                    <span className="quand">{dateHeure(t.cree_le)}</span>
                    <span>
                      <strong>{STATUTS_OF[t.vers_statut]?.libelle ?? t.vers_statut}</strong> — {nom(t.acteur_id)}
                      {t.motif && <div className="champ-aide">{t.motif}</div>}
                    </span>
                  </li>
                ))}
              </ul>
            </Carte>

            {derogation && (
              <DemandeMotif
                titre="Dérogation : sortir des tubes absents du stock"
                consigne="Le stock de tubes deviendra négatif et sera signalé comme écart à régulariser. Le motif est inscrit dans l'historique de l'ordre."
                libelleAction="Accorder la dérogation"
                ton="primaire"
                onFermer={() => setDerogation(false)}
                onConfirmer={async (motif) => {
                  await envoyer(`/api/ordres-fabrication/${id}/valider-matieres`, { derogation_motif: motif });
                  setDerogation(false);
                  await recharger();
                }}
              />
            )}

            {annulation && (
              <DemandeMotif
                titre="Annuler l'ordre de fabrication"
                consigne="Si les tubes étaient déjà sortis, ils sont remis en stock. Une bobine libérée peut servir à un autre ordre."
                libelleAction="Annuler l'ordre"
                onFermer={() => setAnnulation(false)}
                onConfirmer={async (motif) => {
                  await envoyer(`/api/ordres-fabrication/${id}/annuler`, { motif });
                  setAnnulation(false);
                  await recharger();
                }}
              />
            )}
          </>
        )}
      </Chargement>
    </Page>
  );
}
