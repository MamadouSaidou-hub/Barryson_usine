"""En-tetes de securite HTTP et filtrage du nom d'hote.

Middleware ASGI pur : s'applique a toutes les reponses, y compris les erreurs
401/403/404, sans dependre du routeur.
"""

from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings

_ENTETES_COMMUNS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"cross-origin-opener-policy": b"same-origin",
    b"cross-origin-resource-policy": b"same-origin",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
}
# L'API ne sert que du JSON : rien a charger, rien a encadrer.
_CSP_API = b"default-src 'none'; frame-ancestors 'none'"
_HSTS = b"max-age=63072000; includeSubDomains"


class EntetesSecurite:
    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        chemin: str = scope.get("path", "")
        api = chemin.startswith("/api/") and not chemin.startswith("/api/docs")

        async def envoyer(message: Message) -> None:
            if message["type"] == "http.response.start":
                entetes = list(message.get("headers", []))
                presents = {nom.lower() for nom, _ in entetes}
                ajouts = dict(_ENTETES_COMMUNS)
                if api:
                    ajouts[b"content-security-policy"] = _CSP_API
                    # Donnees de gestion : jamais en cache navigateur ni proxy.
                    ajouts[b"cache-control"] = b"no-store"
                if self.hsts:
                    ajouts[b"strict-transport-security"] = _HSTS
                entetes += [(nom, valeur) for nom, valeur in ajouts.items() if nom not in presents]
                message["headers"] = entetes
            await send(message)

        await self.app(scope, receive, envoyer)


class _CorpsTropVolumineux(HTTPException):
    # HTTPException : FastAPI la laisse remonter telle quelle pendant la lecture du corps
    # (toute autre erreur y serait convertie en 400 generique).
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Requête trop volumineuse.")


class LimiteTailleRequete:
    """Refuse (413) un corps de requete trop gros, annonce ou envoye par morceaux.

    Sans cette limite, un seul envoi de plusieurs centaines de megaoctets
    saturerait la memoire du serveur avant meme la validation des donnees.
    """

    def __init__(self, app: ASGIApp, *, maximum: int) -> None:
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for nom, valeur in scope.get("headers", []):
            if nom == b"content-length":
                if not valeur.isdigit() or int(valeur) > self.maximum:
                    await self._refuser(send)
                    return
        recu = 0
        reponse_commencee = False

        async def recevoir() -> Message:
            nonlocal recu
            message = await receive()
            if message["type"] == "http.request":
                recu += len(message.get("body", b""))
                if recu > self.maximum:
                    raise _CorpsTropVolumineux()
            return message

        async def envoyer(message: Message) -> None:
            nonlocal reponse_commencee
            reponse_commencee = reponse_commencee or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, recevoir, envoyer)
        except _CorpsTropVolumineux:
            if not reponse_commencee:
                await self._refuser(send)

    @staticmethod
    async def _refuser(send: Send) -> None:
        corps = '{"detail":"Requête trop volumineuse."}'.encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(corps)).encode())]})
        await send({"type": "http.response.body", "body": corps})


def installer_securite_http(app, reglages: Settings) -> None:
    app.add_middleware(LimiteTailleRequete, maximum=reglages.taille_max_requete_octets)
    app.add_middleware(EntetesSecurite, hsts=reglages.cookie_securise)
    # Refuse les requetes dont l'en-tete Host n'est pas attendu (empoisonnement de cache, DNS rebinding).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=reglages.hotes_autorises)
