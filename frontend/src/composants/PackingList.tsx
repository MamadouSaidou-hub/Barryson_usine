import { useMemo, useState } from "react";
import { envoyer, type S } from "../api";
import { FINITIONS } from "../libelles";
import { Alerte, Badge, Bouton, Champ, Choix, Saisie, Tableau, messageErreur, nombre } from "../ui";

/** Decoupe un texte colle depuis Excel (tabulations) ou un CSV (point-virgule ou virgule). */
function decouper(texte: string): string[][] {
  const lignes = texte.split(/\r?\n/).filter((l) => l.trim());
  const delimiteur = ["\t", ";", ","].find((d) => lignes[0]?.includes(d)) ?? "\t";
  return lignes.map((l) => l.split(delimiteur).map((c) => c.trim().replace(/^"|"$/g, "")));
}

function nombreDe(valeur: string | undefined): number | null {
  if (!valeur) return null;
  const n = Number.parseFloat(valeur.replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

const deviner = (entetes: string[], motif: RegExp) => {
  const i = entetes.findIndex((e) => motif.test(e.toLowerCase()));
  return i >= 0 ? String(i) : "";
};

function devinerFinition(valeur: string): string {
  const t = valeur.toLowerCase();
  if (/gold|golden|\bor\b/.test(t)) return "or_transparent";
  if (/jaune|yellow/.test(t)) return "jaune_transparent";
  if (/clair|clear|white|blanc/.test(t)) return "transparent_clair";
  if (/kaki|khaki|brown|marron/.test(t)) return "kaki_simple";
  return "";
}

export interface PackingPrete {
  importId: string;
  nombre: number;
  conteneur: string;
}

export function PackingList({ fournisseurId, articleId, dateArrivee, finitionAttendue, onPrete, onAnnulee }: {
  fournisseurId: string;
  articleId: string;
  dateArrivee: string;
  finitionAttendue: string | null;
  onPrete: (prete: PackingPrete) => void;
  onAnnulee: () => void;
}) {
  const [texte, setTexte] = useState("");
  const [conteneur, setConteneur] = useState("");
  const [facture, setFacture] = useState("");
  const [colNumero, setColNumero] = useState("");
  const [colPoids, setColPoids] = useState("");
  const [colMetrage, setColMetrage] = useState("");
  const [colFinition, setColFinition] = useState("");
  const [finitions, setFinitions] = useState<Record<string, string>>({});
  const [analyse, setAnalyse] = useState<S["ImportDetail"] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const lignes = useMemo(() => decouper(texte), [texte]);
  const aEntetes = lignes.length > 0 && nombreDe(lignes[0].find((c) => c !== "")) === null;
  const entetes = aEntetes ? lignes[0] : (lignes[0] ?? []).map((_, i) => `Colonne ${i + 1}`);
  const donnees = aEntetes ? lignes.slice(1) : lignes;

  function surColle(valeur: string) {
    setTexte(valeur);
    const l = decouper(valeur);
    if (l.length === 0) return;
    const hasEntetes = nombreDe(l[0].find((c) => c !== "")) === null;
    const e = hasEntetes ? l[0] : l[0].map((_, i) => `Colonne ${i + 1}`);
    const numero = deviner(e, /num|n°|bobine|roll|no\b|id/);
    const poids = deviner(e, /poids|weight|kg|net/);
    const metrage = deviner(e, /m[eé]trage|meter|length|longueur/);
    const finition = deviner(e, /couleur|color|finition|colour/);
    setColNumero(numero || "0");
    setColPoids(poids);
    setColMetrage(metrage);
    setColFinition(finition);
    const lignesDonnees = hasEntetes ? l.slice(1) : l;
    if (finition) {
      const valeurs = [...new Set(lignesDonnees.map((r) => r[Number(finition)] ?? ""))].filter(Boolean);
      setFinitions(Object.fromEntries(valeurs.map((v) => [v, devinerFinition(v)])));
    }
    setAnalyse(null);
  }

  function changerFinition(colonne: string) {
    setColFinition(colonne);
    const valeurs = colonne ? [...new Set(donnees.map((r) => r[Number(colonne)] ?? ""))].filter(Boolean) : [];
    setFinitions(Object.fromEntries(valeurs.map((v) => [v, finitions[v] ?? devinerFinition(v)])));
  }

  const pret = texte && conteneur && colNumero !== "" && colPoids !== "" && donnees.length > 0;

  async function analyser() {
    setEnvoi(true);
    setErreur(null);
    try {
      // Une analyse precedente non utilisee est abandonnee : le conteneur doit rester libre.
      if (analyse) await envoyer(`/api/imports-colisage/${analyse.id}/annuler`);
      const resultat = await envoyer<S["ImportDetail"]>("/api/imports-colisage", {
        conteneur_reference: conteneur,
        numero_facture: facture || null,
        date_reception: dateArrivee,
        fournisseur_id: fournisseurId,
        article_id: articleId,
        lignes: donnees.map((r) => {
          const brute = colFinition ? (r[Number(colFinition)] ?? "") : "";
          const poids = nombreDe(r[Number(colPoids)]);
          const metrage = colMetrage ? nombreDe(r[Number(colMetrage)]) : null;
          return {
            numero_fournisseur: r[Number(colNumero)] || null,
            poids_kg: poids === null ? null : poids.toFixed(2),
            metrage_propre: metrage === null ? null : metrage.toFixed(2),
            couleur_brute: brute || null,
            couleur_finition: finitions[brute] || null,
          };
        }),
      });
      setAnalyse(resultat);
    } catch (e) {
      setErreur(messageErreur(e));
    } finally {
      setEnvoi(false);
    }
  }

  async function abandonner() {
    if (analyse) await envoyer(`/api/imports-colisage/${analyse.id}/annuler`).catch(() => undefined);
    onAnnulee();
  }

  const lignesAvecAnomalies = analyse?.lignes.filter((l) => l.anomalies.length > 0) ?? [];

  return (
    <div className="formulaire">
      <Champ
        etiquette="Collez ici les lignes de la packing list"
        aide="Dans Excel : sélectionnez les lignes (en-têtes compris), copiez, puis collez dans ce cadre. Un fichier CSV fonctionne aussi."
      >
        <textarea className="saisie mono" rows={6} value={texte} onChange={(e) => surColle(e.target.value)} placeholder={"Numero bobine\tCouleur\tPoids net kg\n1\tGold transparent\t251.6"} />
      </Champ>

      {texte && (
        <>
          <div className="rangee">
            <Champ etiquette="Référence du conteneur" aide="Identifiant du lot : un conteneur = un lot.">
              <Saisie value={conteneur} onChange={(e) => setConteneur(e.target.value)} />
            </Champ>
            <Champ etiquette="N° de facture (facultatif)">
              <Saisie value={facture} onChange={(e) => setFacture(e.target.value)} />
            </Champ>
          </div>

          <p className="champ-aide" style={{ margin: 0 }}>
            {donnees.length} ligne(s) détectée(s). Indiquez à quoi correspond chaque colonne :
          </p>
          <div className="rangee">
            {[
              ["Numéro de bobine *", colNumero, setColNumero],
              ["Poids net (kg) *", colPoids, setColPoids],
              ["Métrage (m)", colMetrage, setColMetrage],
            ].map(([libelle, valeur, setter]) => (
              <Champ key={libelle as string} etiquette={libelle as string}>
                <Choix value={valeur as string} onChange={(e) => (setter as (v: string) => void)(e.target.value)}>
                  <option value="">— Aucune —</option>
                  {entetes.map((e, i) => (
                    <option key={i} value={i}>
                      {e}
                    </option>
                  ))}
                </Choix>
              </Champ>
            ))}
            <Champ etiquette="Couleur / finition *">
              <Choix value={colFinition} onChange={(e) => changerFinition(e.target.value)}>
                <option value="">— Aucune —</option>
                {entetes.map((e, i) => (
                  <option key={i} value={i}>
                    {e}
                  </option>
                ))}
              </Choix>
            </Champ>
          </div>

          {Object.keys(finitions).length > 0 && (
            <div>
              <p className="champ-aide">Associez chaque couleur du fournisseur à une finition de l'usine :</p>
              <div className="rangee">
                {Object.keys(finitions).map((valeur) => (
                  <Champ key={valeur} etiquette={`« ${valeur} » est…`}>
                    <Choix value={finitions[valeur]} onChange={(e) => setFinitions({ ...finitions, [valeur]: e.target.value })}>
                      <option value="">— À associer —</option>
                      {Object.entries(FINITIONS).map(([cle, libelle]) => (
                        <option key={cle} value={cle}>
                          {libelle}
                        </option>
                      ))}
                    </Choix>
                  </Champ>
                ))}
              </div>
              {finitionAttendue && (
                <p className="champ-aide">Finition commandée : {FINITIONS[finitionAttendue]}.</p>
              )}
            </div>
          )}

          {!colMetrage && (
            <Alerte ton="alerte">
              Sans colonne de métrage, aucune prévision de fabrication ne sera possible sur ces bobines tant que le
              métrage propre n'est pas renseigné.
            </Alerte>
          )}
          {erreur && <Alerte>{erreur}</Alerte>}

          <div className="actions">
            <Bouton type="button" onClick={analyser} chargement={envoi} disabled={!pret}>
              {analyse ? "Analyser à nouveau" : "Analyser la packing list"}
            </Bouton>
            <Bouton type="button" variante="secondaire" onClick={abandonner}>
              Abandonner
            </Bouton>
          </div>
        </>
      )}

      {analyse && (
        <div className="formulaire">
          {analyse.nb_bloquantes > 0 ? (
            <Alerte>
              <strong>{analyse.nb_bloquantes} anomalie(s) bloquante(s)</strong> : corrigez les colonnes ou le fichier, puis
              relancez l'analyse. Rien n'a été enregistré en stock.
            </Alerte>
          ) : (
            <Alerte ton="ok">
              <strong>{nombre(analyse.nb_lignes)} bobines analysées</strong>, aucune anomalie bloquante.
              {analyse.nb_avertissements > 0 && <> {analyse.nb_avertissements} avertissement(s) à lire ci-dessous.</>}
            </Alerte>
          )}
          {lignesAvecAnomalies.length > 0 && (
            <Tableau colonnes={["Ligne", "Bobine", "Poids", "Métrage", "Anomalies"]} className="">
              {lignesAvecAnomalies.slice(0, 40).map((l) => (
                <tr key={l.rang}>
                  <td>{l.rang}</td>
                  <td>{l.numero_fournisseur ?? "—"}</td>
                  <td>{l.poids_kg ?? "—"}</td>
                  <td>{l.metrage_propre ?? "—"}</td>
                  <td>
                    {l.anomalies.map((a) => (
                      <div key={a.code}>
                        <Badge ton={a.niveau === "bloquante" ? "danger" : "alerte"}>{a.niveau === "bloquante" ? "Bloquant" : "Avertissement"}</Badge>{" "}
                        {a.message}
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
            </Tableau>
          )}
          {lignesAvecAnomalies.length > 40 && <p className="champ-aide">… et {lignesAvecAnomalies.length - 40} autres lignes.</p>}
          {analyse.nb_bloquantes === 0 && (
            <div className="actions">
              <Bouton type="button" onClick={() => onPrete({ importId: analyse.id, nombre: analyse.nb_lignes, conteneur })}>
                Utiliser cette packing list
              </Bouton>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
