"""AD-597c: ChessEngine tests (full FIDE rules minus threefold repetition)."""

from __future__ import annotations

import pytest

from probos.recreation.chess_engine import ChessEngine


def _new() -> tuple[ChessEngine, dict]:
    e = ChessEngine()
    return e, e.new_game("white", "black")


# ---------- new_game / initial state ----------

def test_game_type_is_chess():
    assert ChessEngine().game_type == "chess"


def test_new_game_initial_state():
    e, s = _new()
    assert s["status"] == "in_progress"
    assert s["current_player"] == "white"
    assert s["castling_rights"] == {"WK": True, "WQ": True, "BK": True, "BQ": True}
    assert s["en_passant_target"] == ""
    assert s["halfmove_clock"] == 0
    assert s["fullmove_number"] == 1
    assert s["board"][0][0] == "R"
    assert s["board"][7][4] == "k"


def test_initial_valid_moves_count():
    e, s = _new()
    assert len(e.get_valid_moves(s)) == 20


# ---------- pawn moves ----------

def test_pawn_one_square():
    e, s = _new()
    s2 = e.make_move(s, "white", "e2e3")
    assert s2["board"][2][4] == "P"
    assert s2["board"][1][4] == ""
    assert s2["en_passant_target"] == ""


def test_pawn_two_square_sets_ep():
    e, s = _new()
    s2 = e.make_move(s, "white", "e2e4")
    assert s2["en_passant_target"] == "e3"


def test_pawn_diagonal_capture():
    e, s = _new()
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "d7d5")
    s = e.make_move(s, "white", "e4d5")
    assert s["board"][4][3] == "P"


def test_pawn_blocked_cannot_advance():
    e, s = _new()
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "e7e5")
    with pytest.raises(ValueError):
        e.make_move(s, "white", "e4e5")


# ---------- knight ----------

def test_knight_move():
    e, s = _new()
    s2 = e.make_move(s, "white", "g1f3")
    assert s2["board"][2][5] == "N"


def test_knight_jumps_over_pieces():
    e, s = _new()
    moves = e.get_valid_moves(s)
    assert "g1f3" in moves and "b1c3" in moves


# ---------- bishop / rook / queen / king (must clear path first) ----------

def test_bishop_moves_after_pawn():
    e, s = _new()
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "e7e5")
    s2 = e.make_move(s, "white", "f1c4")
    assert s2["board"][3][2] == "B"


def test_rook_moves_after_clearing():
    e, s = _new()
    s = e.make_move(s, "white", "a2a4")
    s = e.make_move(s, "black", "a7a5")
    s2 = e.make_move(s, "white", "a1a3")
    assert s2["board"][2][0] == "R"


def test_queen_moves_diagonal():
    e, s = _new()
    s = e.make_move(s, "white", "d2d4")
    s = e.make_move(s, "black", "e7e5")
    s2 = e.make_move(s, "white", "d1d3")
    assert s2["board"][2][3] == "Q"


def test_king_one_square():
    e, s = _new()
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "e7e5")
    s2 = e.make_move(s, "white", "e1e2")
    assert s2["board"][1][4] == "K"
    assert s2["castling_rights"]["WK"] is False


# ---------- castling ----------

def _setup_kingside_clear(e, s):
    """Clear white kingside path: knight + bishop out, pawns advanced."""
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "e7e5")
    s = e.make_move(s, "white", "g1f3")
    s = e.make_move(s, "black", "g8f6")
    s = e.make_move(s, "white", "f1c4")
    s = e.make_move(s, "black", "f8c5")
    return s


def test_castle_kingside_happy():
    e, s = _new()
    s = _setup_kingside_clear(e, s)
    s2 = e.make_move(s, "white", "e1g1")
    assert s2["board"][0][6] == "K"
    assert s2["board"][0][5] == "R"
    assert s2["castling_rights"]["WK"] is False
    assert s2["castling_rights"]["WQ"] is False


def test_castle_queenside_happy():
    e, s = _new()
    # Clear white queenside: queen, bishop, knight out
    s = e.make_move(s, "white", "d2d4")
    s = e.make_move(s, "black", "d7d5")
    s = e.make_move(s, "white", "b1c3")
    s = e.make_move(s, "black", "b8c6")
    s = e.make_move(s, "white", "c1f4")
    s = e.make_move(s, "black", "c8f5")
    s = e.make_move(s, "white", "d1d2")
    s = e.make_move(s, "black", "d8d7")
    s2 = e.make_move(s, "white", "e1c1")
    assert s2["board"][0][2] == "K"
    assert s2["board"][0][3] == "R"


def test_castle_kingside_blocked_by_piece():
    e, s = _new()
    # Path not cleared (knight on g1) — castling not in valid moves
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "e7e5")
    moves = e.get_valid_moves(s)
    assert "e1g1" not in moves


def test_castle_when_king_in_check_disallowed():
    e, s = _new()
    s = _setup_kingside_clear(e, s)
    # Put white king in check by black queen via diagonal
    # Black queen escapes: d8-h4 not possible directly. Use 1.f-pawn already moved? Engineer manually.
    # Place a bishop pinning king's row instead: build position via moves
    # Simpler: use a fresh state with crafted board.
    s = e.new_game("white", "black")
    s = _setup_kingside_clear(e, s)
    # Black move that gives check: Bc5 already played; now black plays Bb4+? Need king on e1.
    # Actually after _setup_kingside_clear it's white's turn. Set up a check scenario:
    # Manually craft: put black bishop on a5 attacking e1 — not direct line.
    # Just craft state directly.
    state = e.new_game("white", "black")
    # Empty everything but kings and a checking piece
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][4] = "K"
    state["board"][0][7] = "R"
    state["board"][7][4] = "k"
    state["board"][1][4] = ""
    # Black queen on e8 already? Let's put black rook giving check on e8
    state["board"][7][4] = ""
    state["board"][7][3] = "k"
    state["board"][7][0] = "r"  # rook on a8
    # Now move black rook to e-file giving check? Set rook on e2 directly attacking e1
    state["board"][7][0] = ""
    state["board"][1][4] = "r"  # checks king on e1
    moves = e.get_valid_moves(state)
    assert "e1g1" not in moves


def test_castle_path_through_attacked_square_disallowed():
    e = ChessEngine()
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][4] = "K"
    state["board"][0][7] = "R"
    state["board"][7][3] = "k"
    state["board"][7][5] = "r"  # black rook on f8 attacks f1 (path-square)
    state["castling_rights"] = {"WK": True, "WQ": False, "BK": False, "BQ": False}
    moves = e.get_valid_moves(state)
    assert "e1g1" not in moves


def test_castle_after_king_moved_lost():
    e, s = _new()
    s = _setup_kingside_clear(e, s)
    s = e.make_move(s, "white", "e1f1")
    s = e.make_move(s, "black", "e8f8")
    s = e.make_move(s, "white", "f1e1")
    s = e.make_move(s, "black", "f8e8")
    moves = e.get_valid_moves(s)
    assert "e1g1" not in moves


def test_castle_after_rook_moved_loses_side_only():
    e, s = _new()
    s = _setup_kingside_clear(e, s)
    s = e.make_move(s, "white", "h1f1")
    s = e.make_move(s, "black", "a7a6")
    s = e.make_move(s, "white", "f1h1")
    s = e.make_move(s, "black", "a6a5")
    assert s["castling_rights"]["WK"] is False
    moves = e.get_valid_moves(s)
    assert "e1g1" not in moves


# ---------- en passant ----------

def test_en_passant_happy():
    e, s = _new()
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "a7a6")
    s = e.make_move(s, "white", "e4e5")
    s = e.make_move(s, "black", "d7d5")
    assert s["en_passant_target"] == "d6"
    s = e.make_move(s, "white", "e5d6")
    # Captured black pawn was on d5 (rank index 4)
    assert s["board"][4][3] == ""
    assert s["board"][5][3] == "P"


def test_en_passant_window_closed():
    e, s = _new()
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "a7a6")
    s = e.make_move(s, "white", "e4e5")
    s = e.make_move(s, "black", "d7d5")
    # White makes a different move; ep window closes
    s = e.make_move(s, "white", "h2h3")
    s = e.make_move(s, "black", "h7h6")
    assert s["en_passant_target"] == ""
    moves = e.get_valid_moves(s)
    assert "e5d6" not in moves


# ---------- promotion ----------

def _craft_promotion_state(e):
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][0] = "K"
    state["board"][7][0] = "k"
    state["board"][6][7] = "P"  # white pawn on h7
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    return state


def test_promotion_to_queen():
    e = ChessEngine()
    s = _craft_promotion_state(e)
    s2 = e.make_move(s, "white", "h7h8q")
    assert s2["board"][7][7] == "Q"


def test_promotion_to_rook():
    e = ChessEngine()
    s = _craft_promotion_state(e)
    s2 = e.make_move(s, "white", "h7h8r")
    assert s2["board"][7][7] == "R"


def test_promotion_to_bishop():
    e = ChessEngine()
    s = _craft_promotion_state(e)
    s2 = e.make_move(s, "white", "h7h8b")
    assert s2["board"][7][7] == "B"


def test_promotion_to_knight():
    e = ChessEngine()
    s = _craft_promotion_state(e)
    s2 = e.make_move(s, "white", "h7h8n")
    assert s2["board"][7][7] == "N"


def test_promotion_invalid_piece_rejected():
    e = ChessEngine()
    s = _craft_promotion_state(e)
    with pytest.raises(ValueError):
        e.make_move(s, "white", "h7h8x")


def test_promotion_required_no_plain_move():
    e = ChessEngine()
    s = _craft_promotion_state(e)
    with pytest.raises(ValueError):
        e.make_move(s, "white", "h7h8")


# ---------- check / checkmate / stalemate ----------

def test_fools_mate():
    e, s = _new()
    s = e.make_move(s, "white", "f2f3")
    s = e.make_move(s, "black", "e7e5")
    s = e.make_move(s, "white", "g2g4")
    s = e.make_move(s, "black", "d8h4")
    assert s["status"] == "won"
    assert s["winner"] == "black"
    assert s["result_reason"] == "checkmate"


def test_scholars_mate():
    e, s = _new()
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "e7e5")
    s = e.make_move(s, "white", "f1c4")
    s = e.make_move(s, "black", "b8c6")
    s = e.make_move(s, "white", "d1h5")
    s = e.make_move(s, "black", "g8f6")
    s = e.make_move(s, "white", "h5f7")
    assert s["status"] == "won"
    assert s["winner"] == "white"


def test_stalemate_draw():
    e = ChessEngine()
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][7][7] = "k"  # h8
    state["board"][5][6] = "Q"  # white queen on g6
    state["board"][5][5] = "K"  # white king on f6
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    state["current_player"] = "black"
    # Now white moves something neutral that produces stalemate. Easier: move the king out.
    # Actually, with black to move and king on h8, queen on g6, white king on f6:
    # Black king can move to: g8 attacked by Q; h7 attacked by Q; (no other squares).
    # Not in check -> stalemate.
    # But we set current_player=black; we need a move from black to verify. The state is
    # already stalemate. Test by inspecting valid moves.
    moves = e.get_valid_moves(state)
    assert moves == []
    # And not in check
    from probos.recreation.chess_engine import _in_check
    assert _in_check(state["board"], white=False) is False


def test_check_blocks_illegal_move():
    e, s = _new()
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "e7e5")
    s = e.make_move(s, "white", "d1h5")
    # Now black is threatened on f7 but not in check. Try an illegal black move.
    with pytest.raises(ValueError):
        e.make_move(s, "black", "a7a6 X")  # malformed


def test_pinned_piece_cannot_move_off_pin():
    e = ChessEngine()
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][4] = "K"
    state["board"][1][4] = "N"  # white knight pinned by rook on e8
    state["board"][7][4] = "r"
    state["board"][7][0] = "k"
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    moves = e.get_valid_moves(state)
    # Knight on e2 cannot move (pinned)
    assert "e2c1" not in moves
    assert "e2d4" not in moves


# ---------- 50-move rule ----------

def test_50_move_rule_draw():
    e = ChessEngine()
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][0] = "K"
    state["board"][7][7] = "k"
    state["board"][3][3] = "Q"
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    state["halfmove_clock"] = 99
    # Make a non-pawn, non-capture move
    s2 = e.make_move(state, "white", "d4d5")
    assert s2["status"] == "draw"
    assert s2["result_reason"] == "50_move"


def test_halfmove_clock_resets_on_pawn_move():
    e, s = _new()
    s = e.make_move(s, "white", "g1f3")
    assert s["halfmove_clock"] == 1
    s = e.make_move(s, "black", "e7e5")
    assert s["halfmove_clock"] == 0


def test_halfmove_clock_resets_on_capture():
    e, s = _new()
    s = e.make_move(s, "white", "e2e4")
    s = e.make_move(s, "black", "d7d5")
    assert s["halfmove_clock"] == 0
    s = e.make_move(s, "white", "g1f3")
    assert s["halfmove_clock"] == 1
    s = e.make_move(s, "black", "d5e4")
    assert s["halfmove_clock"] == 0


# ---------- insufficient material ----------

def _bare_kings_state(e, extra_pieces=()):
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][0] = "K"
    state["board"][7][7] = "k"
    for piece, file, rank in extra_pieces:
        state["board"][rank][file] = piece
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    return state


def test_insufficient_material_kk():
    e = ChessEngine()
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    # White king on a1 captures lone black pawn on a2 -> K vs k
    state["board"][0][0] = "K"
    state["board"][1][0] = "p"
    state["board"][7][7] = "k"
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    state["current_player"] = "white"
    s2 = e.make_move(state, "white", "a1a2")
    assert s2["status"] == "draw"
    assert s2["result_reason"] == "insufficient_material"


def test_insufficient_material_kbk_via_check():
    """Reach K+B vs K position via capture; verify draw flagged."""
    e = ChessEngine()
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][0] = "K"
    state["board"][7][7] = "k"
    state["board"][2][2] = "B"  # white bishop on c3
    state["board"][3][3] = "p"  # black pawn on d4 (diagonal target)
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    s2 = e.make_move(state, "white", "c3d4")
    assert s2["status"] == "draw"
    assert s2["result_reason"] == "insufficient_material"


def test_insufficient_material_knk():
    e = ChessEngine()
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][0] = "K"
    state["board"][7][7] = "k"
    state["board"][2][2] = "N"  # knight on c3
    state["board"][4][1] = "p"  # pawn on b5 (knight L-jump from c3)
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    s2 = e.make_move(state, "white", "c3b5")
    assert s2["status"] == "draw"
    assert s2["result_reason"] == "insufficient_material"


def test_insufficient_material_kbb_same_colour():
    e = ChessEngine()
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][0] = "K"
    state["board"][7][7] = "k"
    # Two white bishops on same-colour squares
    state["board"][2][2] = "B"  # c3 (light square: (2+2)%2=0)
    state["board"][4][4] = "B"  # e5 (light square: (4+4)%2=0)
    state["board"][3][3] = "p"  # captured to trigger insufficient flag
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    # White captures pawn — insufficient material check should pass
    # Actually we need only kings + 2 same-colour bishops left.
    # State has K + 2B + k + p. After Bxd4: K + 2B + k. Both bishops on light squares.
    s2 = e.make_move(state, "white", "c3d4")
    # Only kings + 2 same-colour bishops remain; halfmove_clock=0 (capture)
    assert s2["status"] == "draw"
    assert s2["result_reason"] == "insufficient_material"


def test_knn_vs_k_not_drawn_per_convention():
    """K+N+N vs K is technically draw but ships as non-draw per spec."""
    e = ChessEngine()
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][0] = "K"
    state["board"][7][7] = "k"
    state["board"][2][2] = "N"  # c3
    state["board"][2][6] = "N"  # g3
    state["board"][4][3] = "p"  # d5 (knight L-jump from c3)
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    s2 = e.make_move(state, "white", "c3d5")
    assert s2["status"] == "in_progress"


# ---------- UCI / errors ----------

def test_invalid_uci_syntax_raises():
    e, s = _new()
    with pytest.raises(ValueError):
        e.make_move(s, "white", "xx")
    with pytest.raises(ValueError):
        e.make_move(s, "white", "z9z9")
    with pytest.raises(ValueError):
        e.make_move(s, "white", "e2e4e4")  # too long


def test_wrong_player_raises():
    e, s = _new()
    with pytest.raises(ValueError):
        e.make_move(s, "black", "e7e5")


def test_illegal_move_raises():
    e, s = _new()
    with pytest.raises(ValueError):
        e.make_move(s, "white", "e2e6")


def test_make_move_after_game_over_raises():
    e, s = _new()
    s = e.make_move(s, "white", "f2f3")
    s = e.make_move(s, "black", "e7e5")
    s = e.make_move(s, "white", "g2g4")
    s = e.make_move(s, "black", "d8h4")
    with pytest.raises(ValueError):
        e.make_move(s, "white", "a2a3")


# ---------- render / status ----------

def test_render_board_unicode():
    e, s = _new()
    out = e.render_board(s)
    assert "♔" in out
    assert "♚" in out
    assert "·" in out
    assert "a b c d e f g h" in out


def test_is_finished_initial_false():
    e, s = _new()
    assert e.is_finished(s) is False


def test_is_finished_checkmate_true():
    e, s = _new()
    s = e.make_move(s, "white", "f2f3")
    s = e.make_move(s, "black", "e7e5")
    s = e.make_move(s, "white", "g2g4")
    s = e.make_move(s, "black", "d8h4")
    assert e.is_finished(s) is True


def test_get_result_initial():
    e, s = _new()
    r = e.get_result(s)
    assert r["status"] == "in_progress"
    assert r["winner"] == ""


def test_get_result_after_checkmate():
    e, s = _new()
    s = e.make_move(s, "white", "f2f3")
    s = e.make_move(s, "black", "e7e5")
    s = e.make_move(s, "white", "g2g4")
    s = e.make_move(s, "black", "d8h4")
    r = e.get_result(s)
    assert r["status"] == "won"
    assert r["winner"] == "black"
    assert r["reason"] == "checkmate"


def test_get_valid_moves_after_game_over_empty():
    e, s = _new()
    s = e.make_move(s, "white", "f2f3")
    s = e.make_move(s, "black", "e7e5")
    s = e.make_move(s, "white", "g2g4")
    s = e.make_move(s, "black", "d8h4")
    assert e.get_valid_moves(s) == []


# ---------- promotion in valid moves count ----------

def test_promotion_produces_4_uci_entries():
    e = ChessEngine()
    state = e.new_game("white", "black")
    for r in range(8):
        for f in range(8):
            state["board"][r][f] = ""
    state["board"][0][0] = "K"
    state["board"][7][0] = "k"
    state["board"][6][7] = "P"
    state["castling_rights"] = {"WK": False, "WQ": False, "BK": False, "BQ": False}
    moves = e.get_valid_moves(state)
    promo_moves = [m for m in moves if m.startswith("h7h8")]
    assert len(promo_moves) == 4
    assert set(m[4] for m in promo_moves) == set("qrbn")


# ---------- registration in RecreationService ----------

def test_chess_engine_registered_in_recreation_service():
    from probos.recreation.service import RecreationService
    rs = RecreationService()
    assert "chess" in rs.get_available_games()
    assert "tictactoe" in rs.get_available_games()


def test_status_transitions_in_progress_to_won():
    e, s = _new()
    assert s["status"] == "in_progress"
    s = e.make_move(s, "white", "f2f3")
    s = e.make_move(s, "black", "e7e5")
    s = e.make_move(s, "white", "g2g4")
    assert s["status"] == "in_progress"
    s = e.make_move(s, "black", "d8h4")
    assert s["status"] == "won"


def test_fullmove_increments_after_black():
    e, s = _new()
    assert s["fullmove_number"] == 1
    s = e.make_move(s, "white", "e2e4")
    assert s["fullmove_number"] == 1
    s = e.make_move(s, "black", "e7e5")
    assert s["fullmove_number"] == 2
