from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import chess
import uuid
import os

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# stores all active games
games = {}

# maps socket id to game id
players = {}

WIDTH = 800
HEIGHT = 600
PADDLE_HEIGHT = 80
BALL_SIZE = 10
PADDLE_WIDTH = 10

def find_waiting_game():
    for game_id, game in games.items():
        if len(game["players"]) == 1:
            return game_id
    return None

def send_board_state(game_id):
    game = games[game_id]

    # convert board to a simple format the client can understand
    pieces = {}
    for square in chess.SQUARES:
        piece = game["board"].piece_at(square)
        if piece:
            col = chess.square_file(square)
            row = 7 - chess.square_rank(square)
            pieces[f"{col},{row}"] = {
                "type": piece.symbol(),
                "color": "white" if piece.color == chess.WHITE else "black"
            }

    state = {
        "pieces": pieces,
        "turn": "white" if game["board"].turn == chess.WHITE else "black",
        "in_check": game["board"].is_check()
    }

    # send to all players in this game
    for sid in game["players"]:
        emit("board_state", state, to=sid)

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on("connect")
def on_connect(auth=None):
    game_id = find_waiting_game()

    if game_id is None:
        # create a new game
        game_id = str(uuid.uuid4())
        games[game_id] = {
            "board": chess.Board(),
            "players": {}
        }
        games[game_id]["players"][request.sid] = "white"
        players[request.sid] = game_id
        emit("waiting", {"color": "white"})
        print(f"New game created: {game_id}")
    else:
        # join existing game as black
        games[game_id]["players"][request.sid] = "black"
        players[request.sid] = game_id

        white_sid = [sid for sid, color in games[game_id]["players"].items() if color == "white"][0]

        emit("start", {"color": "black"})
        emit("start", {"color": "white"}, to=white_sid)

        send_board_state(game_id)
        print(f"Game {game_id} starting!")

@socketio.on("disconnect")
def on_disconnect():
    if request.sid in players:
        game_id = players[request.sid]
        if game_id in games:
            for sid in games[game_id]["players"]:
                if sid != request.sid:
                    emit("opponent_left", {}, to=sid)
            del games[game_id]
        del players[request.sid]

@socketio.on("move")
def on_move(data):
    if request.sid not in players:
        return

    game_id = players[request.sid]
    game = games[game_id]
    board = game["board"]
    my_color = game["players"][request.sid]

    # make sure it's this player's turn
    if my_color == "white" and board.turn != chess.WHITE:
        return
    if my_color == "black" and board.turn != chess.BLACK:
        return

    try:
        move = chess.Move.from_uci(data["move"])
        if move in board.legal_moves:
            board.push(move)
            send_board_state(game_id)

            # check for game over
            if board.is_checkmate():
                emit("game_over", {"result": "You win!"}, to=request.sid)
                for sid in game["players"]:
                    if sid != request.sid:
                        emit("game_over", {"result": "You lose!"}, to=sid)
            elif board.is_stalemate() or board.is_insufficient_material():
                for sid in game["players"]:
                    emit("game_over", {"result": "Draw!"}, to=sid)
        else:
            emit("invalid_move", {})
    except Exception as e:
        print(f"Move error: {e}")
        emit("invalid_move", {})

@socketio.on("get_moves")
def on_get_moves(data):
    if request.sid not in players:
        return

    game_id = players[request.sid]
    board = games[game_id]["board"]

    # convert col,row to chess square
    col = data["col"]
    row = data["row"]
    square = chess.square(col, 7 - row)

    # get all legal moves from this square
    moves = []
    for move in board.legal_moves:
        if move.from_square == square:
            to_col = chess.square_file(move.to_square)
            to_row = 7 - chess.square_rank(move.to_square)
            moves.append(f"{to_col},{to_row}")

    emit("legal_moves", {"moves": moves})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=True)