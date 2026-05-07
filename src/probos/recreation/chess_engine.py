"""AD-597c: ChessEngine — full FIDE rules minus threefold repetition.

Threefold-repetition draw detection is deferred to AD-597c-1 (needs Zobrist
hashing or canonical FEN-string position-history tracking). v1 ships:

- Move generation per piece (P/N/B/R/Q/K)
- Castling kingside + queenside (blocked-square + king-in-check + path-attacked)
- En passant (single-ply window after 2-square pawn advance)
- Pawn promotion (UCI suffix: e7e8q, e7e8r, e7e8b, e7e8n)
- Check + checkmate + stalemate detection
- 50-move-rule draw (halfmove_clock resets on capture or pawn move)
- Insufficient-material draw (K-K, K-B-K, K-N-K, K-BB-same-colour). K-N-N-K
  is technically draw-by-rule but ships as non-draw per common engine convention.

UCI move syntax: ``"e2e4"``; ``"e7e8q"`` for promotion (q/r/b/n).
"""

from __future__ import annotations

from typing import Any

# Piece codes
WHITE_PIECES = {"P", "N", "B", "R", "Q", "K"}
BLACK_PIECES = {"p", "n", "b", "r", "q", "k"}

# Unicode glyphs
_GLYPH = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
    "": "·",
}

_FILES = "abcdefgh"
_PROMOTION_PIECES = {"q", "r", "b", "n"}


def _is_white(piece: str) -> bool:
    return piece in WHITE_PIECES


def _is_black(piece: str) -> bool:
    return piece in BLACK_PIECES


def _square_to_coords(square: str) -> tuple[int, int] | None:
    """Algebraic ('e4') -> (file, rank). file 0=a, rank 0=white-back-rank."""
    if len(square) != 2:
        return None
    f = square[0]
    r = square[1]
    if f not in _FILES or r not in "12345678":
        return None
    return (_FILES.index(f), int(r) - 1)


def _coords_to_square(file: int, rank: int) -> str:
    return f"{_FILES[file]}{rank + 1}"


def _initial_board() -> list[list[str]]:
    board = [["" for _ in range(8)] for _ in range(8)]
    # White back rank (rank 0)
    board[0] = ["R", "N", "B", "Q", "K", "B", "N", "R"]
    board[1] = ["P"] * 8
    board[6] = ["p"] * 8
    board[7] = ["r", "n", "b", "q", "k", "b", "n", "r"]
    return board


def _clone_board(board: list[list[str]]) -> list[list[str]]:
    return [row[:] for row in board]


def _find_king(board: list[list[str]], white: bool) -> tuple[int, int] | None:
    target = "K" if white else "k"
    for r in range(8):
        for f in range(8):
            if board[r][f] == target:
                return (f, r)
    return None


def _is_square_attacked(
    board: list[list[str]], file: int, rank: int, by_white: bool
) -> bool:
    """Is (file, rank) attacked by `by_white`'s pieces?"""
    enemy_pawn = "P" if by_white else "p"
    pawn_dir = 1 if by_white else -1
    # Pawn attacks come from one rank below (if attacker is white) or above
    for df in (-1, 1):
        pf = file + df
        pr = rank - pawn_dir
        if 0 <= pf < 8 and 0 <= pr < 8 and board[pr][pf] == enemy_pawn:
            return True

    # Knight
    enemy_knight = "N" if by_white else "n"
    for df, dr in (
        (1, 2), (2, 1), (-1, 2), (-2, 1),
        (1, -2), (2, -1), (-1, -2), (-2, -1),
    ):
        nf, nr = file + df, rank + dr
        if 0 <= nf < 8 and 0 <= nr < 8 and board[nr][nf] == enemy_knight:
            return True

    # King (adjacent)
    enemy_king = "K" if by_white else "k"
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if df == 0 and dr == 0:
                continue
            kf, kr = file + df, rank + dr
            if 0 <= kf < 8 and 0 <= kr < 8 and board[kr][kf] == enemy_king:
                return True

    # Sliding: bishop/queen on diagonals
    diag_attackers = ("B", "Q") if by_white else ("b", "q")
    for df, dr in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        f, r = file + df, rank + dr
        while 0 <= f < 8 and 0 <= r < 8:
            piece = board[r][f]
            if piece:
                if piece in diag_attackers:
                    return True
                break
            f += df
            r += dr

    # Sliding: rook/queen on ranks/files
    line_attackers = ("R", "Q") if by_white else ("r", "q")
    for df, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        f, r = file + df, rank + dr
        while 0 <= f < 8 and 0 <= r < 8:
            piece = board[r][f]
            if piece:
                if piece in line_attackers:
                    return True
                break
            f += df
            r += dr

    return False


def _in_check(board: list[list[str]], white: bool) -> bool:
    king = _find_king(board, white)
    if king is None:
        return False
    return _is_square_attacked(board, king[0], king[1], by_white=not white)


def _generate_pseudo_legal_moves(
    state: dict[str, Any], white: bool
) -> list[tuple[str, dict[str, Any]]]:
    """Return list of (uci, move_info) candidate moves ignoring own-king-check."""
    board = state["board"]
    ep_target = state.get("en_passant_target", "")
    castling = state.get("castling_rights", {})
    moves: list[tuple[str, dict[str, Any]]] = []

    own_pieces = WHITE_PIECES if white else BLACK_PIECES
    enemy_pieces = BLACK_PIECES if white else WHITE_PIECES

    for r in range(8):
        for f in range(8):
            piece = board[r][f]
            if piece not in own_pieces:
                continue
            ptype = piece.upper()
            if ptype == "P":
                _gen_pawn(board, f, r, white, ep_target, moves)
            elif ptype == "N":
                _gen_knight(board, f, r, own_pieces, moves)
            elif ptype == "B":
                _gen_slider(board, f, r, own_pieces, enemy_pieces,
                            ((1, 1), (1, -1), (-1, 1), (-1, -1)), moves)
            elif ptype == "R":
                _gen_slider(board, f, r, own_pieces, enemy_pieces,
                            ((1, 0), (-1, 0), (0, 1), (0, -1)), moves)
            elif ptype == "Q":
                _gen_slider(board, f, r, own_pieces, enemy_pieces,
                            ((1, 1), (1, -1), (-1, 1), (-1, -1),
                             (1, 0), (-1, 0), (0, 1), (0, -1)), moves)
            elif ptype == "K":
                _gen_king(board, f, r, own_pieces, moves)
                _gen_castles(board, f, r, white, castling, moves)
    return moves


def _gen_pawn(
    board: list[list[str]],
    f: int,
    r: int,
    white: bool,
    ep_target: str,
    moves: list[tuple[str, dict[str, Any]]],
) -> None:
    direction = 1 if white else -1
    start_rank = 1 if white else 6
    promo_rank = 7 if white else 0
    enemy = BLACK_PIECES if white else WHITE_PIECES

    # Forward 1
    nr = r + direction
    if 0 <= nr < 8 and board[nr][f] == "":
        if nr == promo_rank:
            for promo in "qrbn":
                _add_pawn_move(f, r, f, nr, promo, False, False, moves)
        else:
            _add_pawn_move(f, r, f, nr, "", False, False, moves)
        # Forward 2
        if r == start_rank:
            nr2 = r + 2 * direction
            if board[nr2][f] == "":
                _add_pawn_move(f, r, f, nr2, "", True, False, moves)

    # Captures
    for df in (-1, 1):
        nf = f + df
        nr = r + direction
        if not (0 <= nf < 8 and 0 <= nr < 8):
            continue
        target = board[nr][nf]
        if target in enemy:
            if nr == promo_rank:
                for promo in "qrbn":
                    _add_pawn_move(f, r, nf, nr, promo, False, False, moves)
            else:
                _add_pawn_move(f, r, nf, nr, "", False, False, moves)
        elif ep_target:
            ep_coords = _square_to_coords(ep_target)
            if ep_coords == (nf, nr):
                _add_pawn_move(f, r, nf, nr, "", False, True, moves)


def _add_pawn_move(
    sf: int, sr: int, df: int, dr: int,
    promo: str, two_square: bool, en_passant: bool,
    moves: list[tuple[str, dict[str, Any]]],
) -> None:
    uci = _coords_to_square(sf, sr) + _coords_to_square(df, dr) + promo
    moves.append((uci, {
        "from": (sf, sr),
        "to": (df, dr),
        "piece_type": "P",
        "promotion": promo,
        "two_square_pawn": two_square,
        "en_passant": en_passant,
        "castle": "",
    }))


def _gen_knight(
    board: list[list[str]],
    f: int,
    r: int,
    own_pieces: set[str],
    moves: list[tuple[str, dict[str, Any]]],
) -> None:
    for df, dr in (
        (1, 2), (2, 1), (-1, 2), (-2, 1),
        (1, -2), (2, -1), (-1, -2), (-2, -1),
    ):
        nf, nr = f + df, r + dr
        if not (0 <= nf < 8 and 0 <= nr < 8):
            continue
        if board[nr][nf] in own_pieces:
            continue
        uci = _coords_to_square(f, r) + _coords_to_square(nf, nr)
        moves.append((uci, {
            "from": (f, r), "to": (nf, nr),
            "piece_type": "N", "promotion": "",
            "two_square_pawn": False, "en_passant": False, "castle": "",
        }))


def _gen_slider(
    board: list[list[str]],
    f: int,
    r: int,
    own_pieces: set[str],
    enemy_pieces: set[str],
    directions: tuple[tuple[int, int], ...],
    moves: list[tuple[str, dict[str, Any]]],
) -> None:
    for df, dr in directions:
        nf, nr = f + df, r + dr
        while 0 <= nf < 8 and 0 <= nr < 8:
            target = board[nr][nf]
            if target in own_pieces:
                break
            uci = _coords_to_square(f, r) + _coords_to_square(nf, nr)
            moves.append((uci, {
                "from": (f, r), "to": (nf, nr),
                "piece_type": board[r][f].upper(), "promotion": "",
                "two_square_pawn": False, "en_passant": False, "castle": "",
            }))
            if target in enemy_pieces:
                break
            nf += df
            nr += dr


def _gen_king(
    board: list[list[str]],
    f: int,
    r: int,
    own_pieces: set[str],
    moves: list[tuple[str, dict[str, Any]]],
) -> None:
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if df == 0 and dr == 0:
                continue
            nf, nr = f + df, r + dr
            if not (0 <= nf < 8 and 0 <= nr < 8):
                continue
            if board[nr][nf] in own_pieces:
                continue
            uci = _coords_to_square(f, r) + _coords_to_square(nf, nr)
            moves.append((uci, {
                "from": (f, r), "to": (nf, nr),
                "piece_type": "K", "promotion": "",
                "two_square_pawn": False, "en_passant": False, "castle": "",
            }))


def _gen_castles(
    board: list[list[str]],
    f: int,
    r: int,
    white: bool,
    castling: dict[str, bool],
    moves: list[tuple[str, dict[str, Any]]],
) -> None:
    home_rank = 0 if white else 7
    if r != home_rank or f != 4:
        return
    # King in check? cannot castle.
    if _is_square_attacked(board, 4, home_rank, by_white=not white):
        return

    ks_key = "WK" if white else "BK"
    qs_key = "WQ" if white else "BQ"

    # Kingside: squares f, g must be empty; f, g not attacked.
    if castling.get(ks_key):
        if (
            board[home_rank][5] == ""
            and board[home_rank][6] == ""
            and not _is_square_attacked(board, 5, home_rank, by_white=not white)
            and not _is_square_attacked(board, 6, home_rank, by_white=not white)
        ):
            uci = _coords_to_square(4, home_rank) + _coords_to_square(6, home_rank)
            moves.append((uci, {
                "from": (4, home_rank), "to": (6, home_rank),
                "piece_type": "K", "promotion": "",
                "two_square_pawn": False, "en_passant": False, "castle": "K",
            }))
    # Queenside: squares b, c, d empty; c, d not attacked.
    if castling.get(qs_key):
        if (
            board[home_rank][1] == ""
            and board[home_rank][2] == ""
            and board[home_rank][3] == ""
            and not _is_square_attacked(board, 2, home_rank, by_white=not white)
            and not _is_square_attacked(board, 3, home_rank, by_white=not white)
        ):
            uci = _coords_to_square(4, home_rank) + _coords_to_square(2, home_rank)
            moves.append((uci, {
                "from": (4, home_rank), "to": (2, home_rank),
                "piece_type": "K", "promotion": "",
                "two_square_pawn": False, "en_passant": False, "castle": "Q",
            }))


def _apply_move(
    state: dict[str, Any], info: dict[str, Any]
) -> dict[str, Any]:
    """Apply move described by info to a copy of state. Returns new state."""
    board = _clone_board(state["board"])
    sf, sr = info["from"]
    df, dr = info["to"]
    piece = board[sr][sf]
    is_white = _is_white(piece)
    captured = board[dr][df]
    is_capture = captured != "" or info.get("en_passant", False)

    # En passant capture
    if info.get("en_passant"):
        cap_rank = sr  # Captured pawn on same rank as moving pawn's origin
        board[cap_rank][df] = ""

    # Move piece
    board[dr][df] = piece
    board[sr][sf] = ""

    # Promotion
    promo = info.get("promotion", "")
    if promo:
        board[dr][df] = promo.upper() if is_white else promo.lower()

    # Castling rook movement
    castle = info.get("castle", "")
    if castle == "K":
        rook_rank = dr
        board[rook_rank][5] = board[rook_rank][7]
        board[rook_rank][7] = ""
    elif castle == "Q":
        rook_rank = dr
        board[rook_rank][3] = board[rook_rank][0]
        board[rook_rank][0] = ""

    # Update castling rights
    new_castling = dict(state.get("castling_rights", {}))
    pt = info.get("piece_type", "")
    if pt == "K":
        if is_white:
            new_castling["WK"] = False
            new_castling["WQ"] = False
        else:
            new_castling["BK"] = False
            new_castling["BQ"] = False
    if pt == "R":
        if is_white and sr == 0:
            if sf == 0:
                new_castling["WQ"] = False
            elif sf == 7:
                new_castling["WK"] = False
        elif not is_white and sr == 7:
            if sf == 0:
                new_castling["BQ"] = False
            elif sf == 7:
                new_castling["BK"] = False
    # Capture of a rook on its home square also clears that side's rights
    if captured == "R" and dr == 0:
        if df == 0:
            new_castling["WQ"] = False
        elif df == 7:
            new_castling["WK"] = False
    if captured == "r" and dr == 7:
        if df == 0:
            new_castling["BQ"] = False
        elif df == 7:
            new_castling["BK"] = False

    # En passant target
    new_ep = ""
    if info.get("two_square_pawn"):
        skipped_rank = (sr + dr) // 2
        new_ep = _coords_to_square(sf, skipped_rank)

    # Halfmove clock
    halfmove = state.get("halfmove_clock", 0)
    if pt == "P" or is_capture:
        halfmove = 0
    else:
        halfmove += 1

    # Fullmove
    fullmove = state.get("fullmove_number", 1)
    if not is_white:
        fullmove += 1

    new_state = dict(state)
    new_state["board"] = board
    new_state["castling_rights"] = new_castling
    new_state["en_passant_target"] = new_ep
    new_state["halfmove_clock"] = halfmove
    new_state["fullmove_number"] = fullmove
    return new_state


def _generate_legal_moves(
    state: dict[str, Any], white: bool
) -> list[tuple[str, dict[str, Any]]]:
    pseudo = _generate_pseudo_legal_moves(state, white)
    legal: list[tuple[str, dict[str, Any]]] = []
    for uci, info in pseudo:
        new_state = _apply_move(state, info)
        if not _in_check(new_state["board"], white):
            legal.append((uci, info))
    return legal


def _has_insufficient_material(board: list[list[str]]) -> bool:
    """K-K, K-B-K, K-N-K, K-BB-same-colour-bishops only. Otherwise False."""
    pieces: list[tuple[str, int, int]] = []
    for r in range(8):
        for f in range(8):
            p = board[r][f]
            if p:
                pieces.append((p, f, r))
    # Count non-king pieces by type and side
    non_king = [(p, f, r) for p, f, r in pieces if p.upper() != "K"]
    if len(non_king) == 0:
        return True
    if len(non_king) == 1:
        return non_king[0][0].upper() in ("B", "N")
    if len(non_king) == 2:
        # Both bishops, same colour square
        a, b = non_king
        if a[0].upper() == "B" and b[0].upper() == "B":
            colour_a = (a[1] + a[2]) % 2
            colour_b = (b[1] + b[2]) % 2
            if colour_a == colour_b:
                return True
    return False


class ChessEngine:
    @property
    def game_type(self) -> str:
        return "chess"

    def new_game(self, player_a: str, player_b: str) -> dict[str, Any]:
        return {
            "board": _initial_board(),
            "current_player": player_a,
            "player_a": player_a,
            "player_b": player_b,
            "status": "in_progress",
            "winner": "",
            "castling_rights": {
                "WK": True, "WQ": True, "BK": True, "BQ": True,
            },
            "en_passant_target": "",
            "halfmove_clock": 0,
            "fullmove_number": 1,
            "last_move": "",
            "result_reason": "",
        }

    def make_move(
        self, state: dict[str, Any], player: str, move: str
    ) -> dict[str, Any]:
        if state.get("status") != "in_progress":
            raise ValueError("game is not in progress")
        if player != state.get("current_player"):
            raise ValueError(f"not {player}'s turn")
        white_to_move = player == state.get("player_a")
        # Validate UCI syntax
        if not (4 <= len(move) <= 5):
            raise ValueError(f"invalid UCI move: {move!r}")
        from_sq = move[:2]
        to_sq = move[2:4]
        promo = move[4:5].lower() if len(move) == 5 else ""
        if _square_to_coords(from_sq) is None or _square_to_coords(to_sq) is None:
            raise ValueError(f"invalid UCI square: {move!r}")
        if promo and promo not in _PROMOTION_PIECES:
            raise ValueError(f"invalid promotion piece: {promo!r}")

        legal = _generate_legal_moves(state, white_to_move)
        match = None
        for uci, info in legal:
            if uci == move:
                match = info
                break
            # Allow uppercase promotion suffix
            if promo and uci == move[:4] + promo:
                match = info
                break
        if match is None:
            raise ValueError(f"illegal move: {move}")

        new_state = _apply_move(state, match)
        # Switch player
        next_player = (
            state["player_b"] if white_to_move else state["player_a"]
        )
        new_state["current_player"] = next_player
        new_state["last_move"] = move

        # Check end conditions
        opponent_white = not white_to_move
        opponent_legal = _generate_legal_moves(new_state, opponent_white)
        if not opponent_legal:
            if _in_check(new_state["board"], opponent_white):
                new_state["status"] = "won"
                new_state["winner"] = player
                new_state["result_reason"] = "checkmate"
            else:
                new_state["status"] = "draw"
                new_state["winner"] = ""
                new_state["result_reason"] = "stalemate"
        elif new_state["halfmove_clock"] >= 100:
            new_state["status"] = "draw"
            new_state["winner"] = ""
            new_state["result_reason"] = "50_move"
        elif _has_insufficient_material(new_state["board"]):
            new_state["status"] = "draw"
            new_state["winner"] = ""
            new_state["result_reason"] = "insufficient_material"

        return new_state

    def get_valid_moves(self, state: dict[str, Any]) -> list[str]:
        if state.get("status") != "in_progress":
            return []
        white = state["current_player"] == state["player_a"]
        return [uci for uci, _info in _generate_legal_moves(state, white)]

    def render_board(self, state: dict[str, Any]) -> str:
        board = state["board"]
        lines = []
        lines.append("  a b c d e f g h")
        for r in range(7, -1, -1):
            row = [str(r + 1)]
            for f in range(8):
                row.append(_GLYPH[board[r][f]])
            row.append(str(r + 1))
            lines.append(" ".join(row))
        lines.append("  a b c d e f g h")
        return "\n".join(lines)

    def is_finished(self, state: dict[str, Any]) -> bool:
        return state.get("status") != "in_progress"

    def get_result(self, state: dict[str, Any]) -> dict[str, str]:
        return {
            "status": state.get("status", ""),
            "winner": state.get("winner", ""),
            "reason": state.get("result_reason", ""),
        }
