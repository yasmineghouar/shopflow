"""client.py — appel HTTP minimal qui traduit les erreurs en exceptions Python.

Version projet final du kit du jour 2 : l'URL de base est un paramètre (une par dépendance,
configurable par variable d'environnement, cf. TP 10) et l'en-tête Retry-After est conservé.
"""
import json, socket, urllib.error, urllib.request


class ErreurPermanente(Exception):
    """Erreur 4xx (hors 429) : réessayer ne servirait à rien."""


def appel_http(base, chemin, timeout=2.0, methode="GET", corps=None, entetes=None):
    data = json.dumps(corps).encode() if corps is not None else None
    h = {"Content-Type": "application/json", **(entetes or {})}
    req = urllib.request.Request(base + chemin, data=data, headers=h, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (429, 502, 503, 504):
            erreur = ConnectionError(f"HTTP {e.code}")          # erreur transitoire
            try:
                erreur.retry_after = float(e.headers.get("Retry-After"))
            except (TypeError, ValueError):
                erreur.retry_after = None
            raise erreur from e
        raise ErreurPermanente(f"HTTP {e.code}") from e         # 4xx : erreur permanente
    except (socket.timeout, TimeoutError) as e:
        raise TimeoutError(f"timeout après {timeout}s") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise TimeoutError(f"timeout après {timeout}s") from e
        raise ConnectionError(str(e.reason)) from e
    except (ConnectionError, OSError) as e:                     # reset, refus de connexion
        raise ConnectionError(str(e)) from e
