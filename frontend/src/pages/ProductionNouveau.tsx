import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { envoyer, lire, requete, type S } from "../api";
import { FINITIONS } from "../libelles";
import { Alerte, Bouton, Carte, Champ, Chargement, Choix, Page, Saisie, messageErreur, nombre, useDonnees } from "../ui";

export function ProductionNouveau() {
  const aller = useNavigate();
  const { donnees, erreur, chargement } = useDonnees(async () => {
    const [modeles, disponibles, entamees] = await Promise.all([
      lire<S["ModelePublic"][]>("/api/modeles-ruban"),
      lire<S["BobinePublic"][]>("/api/bobines" + requete({ statut: "disponible" })),
      lire<S["BobinePublic"][]>("/api/bobines" + requete({ statut: "entamee_presente" })),
    ]);
    return {
      modeles: modeles.filter((m) => m.actif),
      bobines: [...entamees, ...disponibles].filter((b) => b.metrage_propre !== null),
    };
  });

  const [modeleId, setModeleId] = useState("");
  const [bobineId, setBobineId] = useState("");
  const [metrage, setMetrage] = useState("");
  const [commentaire, setCommentaire] = useState("");
  const [prevision, setPrevision] = useState<S["PrevisionPublic"] | null>(null);
  const [problemePrevision, setProblemePrevision] = useState<string | null>(null);
  const [probleme, setProbleme] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const modele = donnees?.modeles.find((m) => m.id === modeleId);
  const bobine = donnees?.bobines.find((b) => b.id === bobineId);
  const metrageNum = Number(metrage.replace(",", "."));

  // La prévision se recalcule côté serveur (mêmes règles que la soumission) dès que les trois choix sont faits.
  useEffect(() => {
    setPrevision(null);
    setProblemePrevision(null);
    if (!modeleId || !bobineId || !(metrageNum > 0)) return;
    let courant = true;
    const minuteur = setTimeout(() => {
      envoyer<S["PrevisionPublic"]>("/api/production/previsions", {
        modele_id: modeleId,
        bobine_id: bobineId,
        metrage_engage: metrage.trim().replace(",", "."),
      })
        .then((p) => courant && setPrevision(p))
        .catch((e) => courant && setProblemePrevision(messageErreur(e)));
    }, 350);
    return () => {
      courant = false;
      clearTimeout(minuteur);
    };
  }, [modeleId, bobineId, metrage, metrageNum]);

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setProbleme(null);
    try {
      const ordre = await envoyer<S["OrdreDetail"]>("/api/ordres-fabrication", {
        modele_id: modeleId,
        bobine_id: bobineId,
        metrage_engage: metrage.trim().replace(",", "."),
        commentaire: commentaire.trim() || null,
      });
      aller(`/production/${ordre.id}`);
    } catch (err) {
      setProbleme(messageErreur(err));
      setEnvoi(false);
    }
  }

  return (
    <Page
      titre="Préparer un ordre de fabrication"
      sousTitre="Choisissez le ruban à fabriquer, la bobine à découper et le métrage à y engager."
      actions={<Link to="/production">← Tous les ordres</Link>}
    >
      <Chargement erreur={erreur} chargement={chargement}>
        {donnees && (
          <form onSubmit={soumettre} className="grille deux">
            <Carte titre="Fabrication">
            <div className="formulaire">
              <Champ etiquette="Modèle de ruban" aide={modele && !modele.complet ? "Fiche incomplète : moule, produit fini ou tube manquant." : undefined}>
                <Choix value={modeleId} onChange={(e) => setModeleId(e.target.value)}>
                  <option value="">— Choisir —</option>
                  {donnees.modeles.map((m) => (
                    <option key={m.id} value={m.id} disabled={!m.complet}>
                      {m.code} — {m.nom}
                      {m.complet ? "" : " (fiche incomplète)"}
                    </option>
                  ))}
                </Choix>
              </Champ>
              <Champ etiquette="Bobine à découper" aide="Seules les bobines avec un métrage propre connu sont proposées.">
                <Choix value={bobineId} onChange={(e) => setBobineId(e.target.value)}>
                  <option value="">— Choisir —</option>
                  {donnees.bobines.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.numero_fournisseur} · {FINITIONS[b.couleur_finition]} · {nombre(b.metrage_propre, 0)} m
                      {b.statut === "entamee_presente" ? " · entamée" : ""}
                    </option>
                  ))}
                </Choix>
              </Champ>
              <Champ
                etiquette="Métrage engagé (m)"
                aide={bobine ? `Au plus ${nombre(bobine.metrage_propre, 0)} m (métrage propre de la bobine).` : undefined}
              >
                <Saisie inputMode="decimal" value={metrage} onChange={(e) => setMetrage(e.target.value)} />
              </Champ>
              <Champ etiquette="Commentaire">
                <Saisie value={commentaire} onChange={(e) => setCommentaire(e.target.value)} />
              </Champ>
              {probleme && <Alerte>{probleme}</Alerte>}
              <div className="actions">
                <Bouton type="submit" chargement={envoi} disabled={!modeleId || !bobineId || !(metrageNum > 0)}>
                  Enregistrer le brouillon
                </Bouton>
              </div>
            </div>
            </Carte>

            <Carte titre="Prévision">
              {problemePrevision && <Alerte>{problemePrevision}</Alerte>}
              {!prevision && !problemePrevision && <p className="champ-aide">La prévision apparaît dès que le modèle, la bobine et le métrage sont choisis.</p>}
              {prevision && (
                <>
                  <dl className="definition">
                    <dt>Tours complets</dt>
                    <dd>{nombre(prevision.tours_complets)}</dd>
                    <dt>Pièces théoriques</dt>
                    <dd>
                      {nombre(prevision.pieces_theoriques)} ({prevision.pieces_par_tour} par tour)
                    </dd>
                    <dt>Cartons complets</dt>
                    <dd>
                      {nombre(prevision.cartons_complets)} ({prevision.pieces_par_carton} pièces par carton)
                    </dd>
                    <dt>Pièces hors carton</dt>
                    <dd>{nombre(prevision.pieces_restantes)}</dd>
                    <dt>Tubes nécessaires</dt>
                    <dd>{nombre(prevision.pieces_theoriques)}</dd>
                  </dl>
                  {prevision.alertes.map((a) => (
                    <Alerte key={a.code} ton="alerte">
                      {a.message}
                    </Alerte>
                  ))}
                </>
              )}
            </Carte>
          </form>
        )}
      </Chargement>
    </Page>
  );
}
