"""Outils de transaction partages par les services metier."""

import functools
from collections.abc import Callable


def transactionnel[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    """Toute erreur annule la transaction : un changement fait en memoire avant l'echec ne doit
    jamais pouvoir etre enregistre par une operation suivante sur la meme session.

    Le premier argument de l'operation doit etre la session SQLAlchemy.
    """

    @functools.wraps(operation)
    def enveloppe(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return operation(*args, **kwargs)
        except Exception:
            args[0].rollback()  # type: ignore[attr-defined]
            raise

    return enveloppe
