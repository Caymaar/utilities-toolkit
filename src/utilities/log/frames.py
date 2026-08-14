"""Rendu de DataFrames et de séries dans le log lui-même.

Deux outils, dans l'ordre où il faut y penser :

- :func:`spark` — une sparkline en blocs Unicode, **~12 µs pour 300 points**,
  sans aucune dépendance, qui tient sur une ligne et reste greppable. C'est le
  premier réflexe : dans la grande majorité des cas, la question qu'on se pose
  en lisant un log de pipeline est « est-ce que la distribution a une tête
  normale ? », et une sparkline y répond, pour 145 fois moins cher qu'un graphe
  plotext.
- :func:`log_frame` — le rendu d'un DataFrame polars ou pandas au niveau
  ``DATAFRAME``, en quatre modes.

Ni polars ni pandas ne sont importés par ce module : ils sont détectés sur
l'objet reçu. Si vous tenez un DataFrame, le paquet qui le fabrique est déjà
chargé.
"""

from __future__ import annotations

import contextlib
import io
import math
import sys
from typing import Any, Iterator, List, Optional, Sequence

from utilities.log.levels import DATAFRAME

__all__ = ["spark", "log_frame", "MODES"]

#: Du plus bas au plus haut. Huit paliers, c'est ce que donne Unicode.
_BLOCKS = "▁▂▃▄▅▆▇█"

MODES = ("head", "tail", "full", "describe")

#: Plafonds par défaut du mode ``full``. Surchargeables par appel, jamais
#: supprimables.
DEFAULT_MAX_ROWS = 200
DEFAULT_MAX_COLS = 40

#: Largeur fixée explicitement : sans ça, le rendu dépend du terminal détecté
#: au moment du log, donc diffère entre une console et un fichier.
DEFAULT_WIDTH = 200

#: Un `RichHandler` configuré avec ``markup=True`` interprète les crochets du
#: message. Or ici le message contient des **données** : une cellule qui vaut
#: ``[/bold]`` ferait lever `MarkupError` à l'appel de log, et une colonne
#: nommée ``ret[bps]`` s'afficherait tronquée. Le rendu d'un frame n'est jamais
#: du markup ; on le dit enregistrement par enregistrement, sans toucher au
#: réglage global de l'hôte.
_SANS_MARKUP = {"markup": False, "highlighter": None}


# --------------------------------------------------------------------------- #
# Sparkline
# --------------------------------------------------------------------------- #


def spark(values: Sequence[Any], n: int = 24) -> str:
    """Sparkline en blocs Unicode, sur une seule ligne.

    ``n`` est le nombre de caractères visés ; une série plus longue est
    sous-échantillonnée en conservant ses deux extrémités. Les valeurs non
    numériques ou non finies (``None``, ``NaN``, ``inf``) sont ignorées.

    Une série constante rend ``▁▁▁`` — la sparkline seule ne dit pas à quelle
    hauteur elle est plate, d'où l'usage recommandé avec son cadrage :

        log.info("nav n=%d %s [%.2f, %.2f]", len(v), spark(v), min(v), max(v))

    Renvoie une chaîne vide si rien d'exploitable n'est passé.
    """
    clean: List[float] = []
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            clean.append(f)

    if not clean:
        return ""
    if n < 1:
        return ""

    size = len(clean)
    if size > n:
        if n == 1:
            clean = [clean[-1]]
        else:
            # Indices étalés sur toute la série, extrémités comprises : prendre
            # `clean[::pas]` perdrait la queue dès que la série n'est pas un
            # multiple exact de n.
            clean = [clean[i * (size - 1) // (n - 1)] for i in range(n)]

    lo = min(clean)
    span = max(clean) - lo
    if span <= 0:
        return _BLOCKS[0] * len(clean)

    top = len(_BLOCKS) - 1
    return "".join(_BLOCKS[int((v - lo) / span * top + 0.5)] for v in clean)


# --------------------------------------------------------------------------- #
# Détection, sans importer polars ni pandas
# --------------------------------------------------------------------------- #


def _flavour(df: Any) -> str:
    """``"polars"``, ``"pandas"`` ou ``"unknown"``, sans aucun import."""
    root = type(df).__module__.split(".")[0]
    if root in ("polars", "pandas") and root in sys.modules:
        return root
    return "unknown"


def _is_lazy(df: Any) -> bool:
    """Un ``LazyFrame`` a ``collect`` **et** ``explain`` ; un ``DataFrame`` n'a ni l'un ni l'autre."""
    return hasattr(df, "collect") and hasattr(df, "explain")


def _shape(df: Any) -> Optional[tuple]:
    shape = getattr(df, "shape", None)
    if isinstance(shape, tuple) and len(shape) == 2:
        return shape
    return None


@contextlib.contextmanager
def _display_config(flavour: str, rows: int, cols: int, width: int) -> Iterator[None]:
    """Configuration d'affichage **scopée**.

    Muter la config globale depuis un logger changerait les ``print`` de
    l'appelant. Les deux moteurs fournissent un context manager qui restaure,
    y compris si le rendu lève.
    """
    if flavour == "polars":
        pl = sys.modules.get("polars")
        if pl is not None and hasattr(pl, "Config"):
            with pl.Config(
                tbl_rows=rows,
                tbl_cols=cols,
                tbl_width_chars=width,
                fmt_str_lengths=50,
            ):
                yield
            return
    elif flavour == "pandas":
        pd = sys.modules.get("pandas")
        if pd is not None and hasattr(pd, "option_context"):
            with pd.option_context(
                "display.max_rows", rows,
                "display.max_columns", cols,
                "display.width", width,
            ):
                yield
            return
    yield


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #


def _slice_for(df: Any, mode: str, n: int, max_rows: int) -> Any:
    if mode == "head":
        return df.head(n)
    if mode == "tail":
        return df.tail(n)
    if mode == "describe":
        return df.describe()
    # full : on borne à min(plafond, hauteur). Jamais -1, jamais illimité —
    # c'est nous qui levons le garde-fou natif, donc c'est à nous de le
    # remplacer par un autre.
    return df.head(max_rows)


def _rich_table(frame: Any, flavour: str, width: int, max_cols: int) -> Optional[str]:
    """Rendu Rich de la tranche **déjà tronquée**. ``None`` si impossible."""
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:  # pragma: no cover - rich est une dépendance obligatoire
        return None

    columns = [str(c) for c in (list(getattr(frame, "columns", [])) or [])]
    if not columns:
        return None

    if flavour == "polars" and hasattr(frame, "rows"):
        rows = frame.rows()
    elif flavour == "pandas" and hasattr(frame, "itertuples"):
        rows = [tuple(r) for r in frame.itertuples(index=False)]
        # L'index pandas porte l'information en mode describe — count, mean,
        # std... Sans lui, la table Rich n'est qu'une colonne de nombres
        # anonymes, là où le repr natif montre les libellés.
        index = list(getattr(frame, "index", []))
        if index and index != list(range(len(index))):
            columns.insert(0, str(getattr(frame.index, "name", "") or ""))
            rows = [(str(cle),) + ligne for cle, ligne in zip(index, rows)]
    else:
        return None

    # Le plafond de colonnes vaut pour ce rendu aussi : sans ça, la table
    # afficherait les 60 colonnes tout en annonçant qu'elle en a omis 20.
    if len(columns) > max_cols:
        columns = columns[:max_cols]
        rows = [ligne[:max_cols] for ligne in rows]

    table = Table(header_style="bold", show_lines=False)
    for name in columns:
        table.add_column(name, overflow="fold")
    for row in rows:
        table.add_row(*(("" if c is None else str(c)) for c in row))

    # no_color : la sortie part dans un log, pas sur un terminal. Sans ça, il
    # faudrait compter sur AnsiStrippingFormatter pour rattraper le coup.
    #
    # force_jupyter=False : dans un noyau, Rich bascule en mode Jupyter **même
    # avec un `file=`**, et `print()` appelle alors `display()` sans jamais
    # écrire dans le tampon. La table s'afficherait hors du log, et
    # l'enregistrement partirait avec un corps vide.
    console = Console(
        file=io.StringIO(),
        width=width,
        no_color=True,
        force_jupyter=False,
        force_terminal=False,
    )
    console.print(table)
    return console.file.getvalue().rstrip("\n") or None  # type: ignore[union-attr]


def log_frame(
    log: Any,
    df: Any,
    *,
    mode: str = "head",
    n: int = 10,
    label: Optional[str] = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cols: int = DEFAULT_MAX_COLS,
    width: int = DEFAULT_WIDTH,
    rich: bool = False,
) -> None:
    """Logge un DataFrame au niveau ``DATAFRAME`` (8).

    ``mode`` vaut ``"head"``, ``"tail"``, ``"full"`` ou ``"describe"``. ``n`` ne
    s'applique qu'à ``head`` et ``tail`` ; le plafond ``max_rows`` s'applique
    toujours et ne peut pas être désactivé.

    Un ``LazyFrame`` n'est **jamais** matérialisé : son plan d'exécution est
    logué à la place. Déclencher un ``collect()`` depuis un log serait le pire
    défaut possible de ce module.

    ``log`` est explicite : le module ne choisit pas le namespace à votre place.
    La convention est ``<votre_app>.data``.

    Rien n'est construit si le niveau est éteint — c'est le seul coût dans ce
    cas, ~250 ns.
    """
    if not log.isEnabledFor(DATAFRAME):
        return

    if mode not in MODES:
        raise ValueError("mode=%r inconnu, attendu l'un de %s" % (mode, list(MODES)))

    name = label or type(df).__name__

    if _is_lazy(df):
        # P3 : le plan est souvent plus instructif que les données, et il ne
        # coûte rien. Aucun collect(), dans aucun mode.
        try:
            plan = df.explain()
        except Exception as exc:  # plan indisponible : on le dit, on n'exécute pas
            plan = "explain() indisponible : %s: %s" % (type(exc).__name__, exc)
        log.log(
            DATAFRAME,
            "%s | LazyFrame non matérialisé — plan d'exécution :\n%s",
            name, plan,
            extra=_SANS_MARKUP,
        )
        return

    flavour = _flavour(df)
    shape = _shape(df)
    rows_total = shape[0] if shape else None
    cols_total = shape[1] if shape else None

    frame = _slice_for(df, mode, n, max_rows)

    # La hauteur à afficher est celle de **la tranche**, pas celle de la source.
    # `describe()` fabrique ses propres lignes — huit en pandas, neuf en polars —
    # et les borner à la hauteur du frame d'origine tronquait le résumé d'un
    # petit tableau à ses trois premières statistiques.
    forme_rendue = _shape(frame)
    shown_rows = forme_rendue[0] if forme_rendue else max_rows

    body = None
    if rich:
        with _display_config(flavour, shown_rows, max_cols, width):
            body = _rich_table(frame, flavour, width, max_cols)
    if not body:  # rendu Rich impossible, ou vide : on retombe sur le natif
        with _display_config(flavour, shown_rows, max_cols, width):
            body = str(frame)

    entete = "%s | %s | %s" % (
        name,
        "%d x %d" % shape if shape else "forme inconnue",
        "mode=%s" % mode if mode not in ("head", "tail") else "mode=%s n=%d" % (mode, n),
    )

    notes = []
    if mode == "full" and rows_total is not None and rows_total > max_rows:
        notes.append(
            "%d lignes omises sur %d (plafond max_rows=%d)"
            % (rows_total - max_rows, rows_total, max_rows)
        )
    if cols_total is not None and cols_total > max_cols:
        notes.append(
            "%d colonnes omises sur %d (plafond max_cols=%d)"
            % (cols_total - max_cols, cols_total, max_cols)
        )

    if notes:
        body = "%s\n... %s" % (body, " ; ".join(notes))

    log.log(DATAFRAME, "%s\n%s", entete, body, extra=_SANS_MARKUP)
