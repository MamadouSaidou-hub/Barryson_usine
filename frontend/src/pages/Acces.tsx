import { useState, type FormEvent, type ReactNode } from "react";
import { envoyer, type S } from "../api";
import { useAuth } from "../auth";
import { Alerte, Bouton, Carte, Champ, messageErreur, Saisie } from "../ui";

function Ecran({ titre, sousTitre, children }: { titre: string; sousTitre?: string; children: ReactNode }) {
  return (
    <main className="connexion">
      <Carte>
        <h1>{titre}</h1>
        {sousTitre && <p className="soustitre">{sousTitre}</p>}
        <div style={{ marginTop: 18 }}>{children}</div>
      </Carte>
    </main>
  );
}

export function Connexion() {
  const { connecter } = useAuth();
  const [identifiant, setIdentifiant] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [code, setCode] = useState("");
  const [etapeCode, setEtapeCode] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      const resultat = await connecter(identifiant, motDePasse, etapeCode ? code : undefined);
      if (resultat === "code_requis") setEtapeCode(true);
    } catch (err) {
      setErreur(messageErreur(err));
      if (etapeCode) setCode("");
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <Ecran titre="Barryson ERP" sousTitre="Group BARRYSON Sarl — gestion de l'usine">
      <form className="formulaire" onSubmit={soumettre}>
        <Champ etiquette="Identifiant">
          <Saisie
            value={identifiant}
            autoComplete="username"
            autoFocus
            disabled={etapeCode}
            onChange={(e) => setIdentifiant(e.target.value)}
          />
        </Champ>
        <Champ etiquette="Mot de passe">
          <Saisie
            type="password"
            value={motDePasse}
            autoComplete="current-password"
            disabled={etapeCode}
            onChange={(e) => setMotDePasse(e.target.value)}
          />
        </Champ>
        {etapeCode && (
          <>
            <Alerte ton="info">
              Votre compte est protégé par un second facteur. Saisissez le code à 6 chiffres affiché par
              l'application d'authentification de votre téléphone.
            </Alerte>
            <Champ etiquette="Code à 6 chiffres">
              <Saisie
                value={code}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                autoFocus
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              />
            </Champ>
          </>
        )}
        {erreur && <Alerte>{erreur}</Alerte>}
        <Bouton type="submit" chargement={envoi} disabled={!identifiant || !motDePasse || (etapeCode && code.length !== 6)}>
          Se connecter
        </Bouton>
      </form>
    </Ecran>
  );
}

export function ChangerMotDePasse() {
  const { appliquer, deconnecter } = useAuth();
  const [actuel, setActuel] = useState("");
  const [nouveau, setNouveau] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      appliquer(await envoyer<S["ReponseSession"]>("/api/auth/mot-de-passe", { actuel, nouveau }));
    } catch (err) {
      setErreur(messageErreur(err));
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <Ecran titre="Choisissez votre mot de passe" sousTitre="Le mot de passe temporaire ne sert qu'à la première connexion.">
      <form className="formulaire" onSubmit={soumettre}>
        <Champ etiquette="Mot de passe temporaire">
          <Saisie type="password" value={actuel} autoComplete="current-password" onChange={(e) => setActuel(e.target.value)} />
        </Champ>
        <Champ etiquette="Nouveau mot de passe" aide="12 caractères minimum. Une phrase de plusieurs mots est idéale.">
          <Saisie type="password" value={nouveau} autoComplete="new-password" onChange={(e) => setNouveau(e.target.value)} />
        </Champ>
        <Champ
          etiquette="Confirmation"
          erreur={confirmation && confirmation !== nouveau ? "Les deux saisies diffèrent." : undefined}
        >
          <Saisie type="password" value={confirmation} autoComplete="new-password" onChange={(e) => setConfirmation(e.target.value)} />
        </Champ>
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="actions">
          <Bouton type="submit" chargement={envoi} disabled={!actuel || nouveau.length < 12 || nouveau !== confirmation}>
            Enregistrer
          </Bouton>
          <Bouton type="button" variante="secondaire" onClick={deconnecter}>
            Se déconnecter
          </Bouton>
        </div>
      </form>
    </Ecran>
  );
}

export function ConfigurerDoubleFacteur() {
  const { appliquer, deconnecter } = useAuth();
  const [config, setConfig] = useState<S["ConfigurationDoubleFacteur"] | null>(null);
  const [code, setCode] = useState("");
  const [copiee, setCopiee] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function demarrer() {
    setEnvoi(true);
    setErreur(null);
    try {
      setConfig(await envoyer<S["ConfigurationDoubleFacteur"]>("/api/auth/double-facteur/initialiser"));
    } catch (err) {
      setErreur(messageErreur(err));
    } finally {
      setEnvoi(false);
    }
  }

  async function activer(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      appliquer(await envoyer<S["ReponseSession"]>("/api/auth/double-facteur/activer", { code }));
    } catch (err) {
      setErreur(messageErreur(err));
    } finally {
      setEnvoi(false);
    }
  }

  const groupes = config?.secret.match(/.{1,4}/g)?.join(" ");

  return (
    <Ecran
      titre="Protégez votre compte"
      sousTitre="Votre fonction exige un second facteur : un code à 6 chiffres généré par votre téléphone."
    >
      {!config ? (
        <div className="formulaire">
          <p>
            Installez une application d'authentification (Google Authenticator, Microsoft Authenticator…), puis
            cliquez sur « Commencer » pour obtenir votre clé personnelle.
          </p>
          {erreur && <Alerte>{erreur}</Alerte>}
          <div className="actions">
            <Bouton onClick={demarrer} chargement={envoi}>
              Commencer
            </Bouton>
            <Bouton variante="secondaire" onClick={deconnecter}>
              Se déconnecter
            </Bouton>
          </div>
        </div>
      ) : (
        <form className="formulaire" onSubmit={activer}>
          <p>
            Dans l'application : <strong>Ajouter un compte → Saisir une clé</strong>, nom « Barryson ERP », type
            « basé sur l'heure », puis recopiez cette clé :
          </p>
          <div className="secret">{groupes}</div>
          <div className="actions">
            <Bouton
              type="button"
              variante="secondaire"
              onClick={() => {
                navigator.clipboard
                  ?.writeText(config.secret)
                  .then(() => setCopiee(true))
                  .catch(() => setCopiee(false));
              }}
            >
              {copiee ? "Clé copiée ✓" : "Copier la clé"}
            </Bouton>
          </div>
          <Champ etiquette="Code affiché par l'application" aide="Cela confirme que la clé est bien enregistrée.">
            <Saisie
              value={code}
              inputMode="numeric"
              maxLength={6}
              autoFocus
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            />
          </Champ>
          {erreur && <Alerte>{erreur}</Alerte>}
          <Bouton type="submit" chargement={envoi} disabled={code.length !== 6}>
            Activer
          </Bouton>
        </form>
      )}
    </Ecran>
  );
}
