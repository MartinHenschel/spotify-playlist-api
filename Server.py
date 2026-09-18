"""
API para criar playlists no Spotify a partir de uma lista de musicas.
Usa APENAS bibliotecas nativas do Python (nao precisa de pip install).

Como usar:
  1. Edite config.py com seu CLIENT_ID e CLIENT_SECRET do Spotify.
  2. Rode: python server.py
  3. Abra no navegador: http://127.0.0.1:8888/login
  4. Depois de autorizar, envie um POST para /create-playlist (veja README.md)
"""

import base64
import json
import urllib.request
import urllib.parse
import urllib.error
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import Config as config

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
SCOPES = "playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative"

# Guarda os tokens em memoria (uso pessoal / demo, 1 usuario por vez)
tokens = {"access_token": None, "refresh_token": None, "expires_at": 0}


def generate_playlist_request(prompt):
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY.startswith("sua_"):
        raise RuntimeError("GEMINI_API_KEY nao configurada no arquivo .env.")

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": (
                    "Voce e um curador musical. Responda somente JSON valido, sem markdown, "
                    "com este formato: {\"playlist_name\": string, \"tracks\": "
                    "[{\"artist\": string, \"title\": string}]}. "
                    "Gere exatamente a quantidade pedida quando for possivel. "
                    "Nao invente faixas; prefira musicas conhecidas e existentes.\n\n"
                    f"Pedido do usuario: {prompt}"
                )}],
            },
        ],
        "generationConfig": {
            "temperature": 0.4,
            "responseMimeType": "application/json",
        },
    }
    models = [config.GEMINI_MODEL]
    if config.GEMINI_FALLBACK_MODEL and config.GEMINI_FALLBACK_MODEL not in models:
        models.append(config.GEMINI_FALLBACK_MODEL)
    result = None
    last_error = None
    for model in models:
        for attempt in range(3):
            request = urllib.request.Request(
                f"{GEMINI_API_URL}/{model}:generateContent?"
                + urllib.parse.urlencode({"key": config.GEMINI_API_KEY}),
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
            )
            request.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(request) as response:
                    result = json.loads(response.read())
                break
            except urllib.error.HTTPError as error:
                details = error.read().decode("utf-8")
                last_error = f"Erro Gemini API ({error.code}) no modelo {model}: {details}"
                if error.code not in (429, 503):
                    break
                time.sleep(2 ** attempt)
        if result is not None:
            break
    if result is None:
        raise RuntimeError(last_error or "Gemini nao retornou uma resposta.")

    content = result["candidates"][0]["content"]["parts"][0]["text"]
    try:
        generated = json.loads(content)
        tracks = generated.get("tracks", [])
        songs = [
            f"{track['artist']} - {track['title']}"
            for track in tracks
            if track.get("artist") and track.get("title")
        ]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Resposta invalida do Gemini: {error}")
    if not songs:
        raise RuntimeError("O Gemini nao retornou musicas validas.")
    return {"name": generated.get("playlist_name", "Playlist gerada"), "songs": songs}


def spotify_request(method, path, body=None, retry=True):
    """Faz uma requisicao autenticada para a API do Spotify."""
    ensure_valid_token()
    url = f"{SPOTIFY_API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {tokens['access_token']}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        raise RuntimeError(f"Erro Spotify API ({e.code}) em {path}: {err_body}")


def ensure_valid_token():
    if not tokens["access_token"]:
        raise RuntimeError("Nao autenticado. Acesse /login primeiro.")
    if time.time() >= tokens["expires_at"] - 60:
        refresh_access_token()


def refresh_access_token():
    auth_header = base64.b64encode(
        f"{config.CLIENT_ID}:{config.CLIENT_SECRET}".encode()
    ).decode()
    data = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
    ).encode()
    req = urllib.request.Request(SPOTIFY_TOKEN_URL, data=data, method="POST")
    req.add_header("Authorization", f"Basic {auth_header}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as resp:
        payload = json.loads(resp.read())
    tokens["access_token"] = payload["access_token"]
    tokens["expires_at"] = time.time() + payload["expires_in"]


def search_tracks(songs):
    encontradas, nao_encontradas = [], []
    for query in songs:
        q = urllib.parse.urlencode({"q": query, "type": "track", "limit": 1})
        result = spotify_request("GET", f"/search?{q}")
        items = result.get("tracks", {}).get("items", [])
        if items:
            track = items[0]
            encontradas.append(
                {
                    "query": query,
                    "uri": track["uri"],
                    "nome": track["name"],
                    "artista": ", ".join(a["name"] for a in track["artists"]),
                }
            )
        else:
            nao_encontradas.append(query)
    return encontradas, nao_encontradas


def get_playlist_id(value):
    value = value.strip()
    if "/playlist/" in value:
        value = urllib.parse.urlparse(value).path.rstrip("/").split("/")[-1]
    if "?" in value:
        value = value.split("?", 1)[0]
    if not value or len(value) != 22:
        raise ValueError("Informe uma URL ou ID de playlist valido.")
    return value


def get_playlist_track_uris(playlist_id):
    uris = set()
    offset = 0
    while True:
        query = urllib.parse.urlencode({"limit": 50, "offset": offset})
        result = spotify_request("GET", f"/playlists/{playlist_id}/items?{query}")
        items = result.get("items", [])
        for entry in items:
            item = entry.get("item") or entry.get("track") or {}
            if item.get("uri"):
                uris.add(item["uri"])
        if not result.get("next") or not items:
            return uris
        offset += len(items)


def get_user_playlists():
    playlists = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({"limit": 50, "offset": offset})
        result = spotify_request("GET", f"/me/playlists?{query}")
        items = result.get("items", [])
        playlists.extend(
            {
                "id": item["id"],
                "name": item["name"],
                "tracks": item.get("items", {}).get("total", 0),
            }
            for item in items
        )
        if not result.get("next") or not items:
            return playlists
        offset += len(items)


def add_tracks_to_playlist(playlist_id, tracks):
    uris = [t["uri"] for t in tracks]
    for i in range(0, len(uris), 100):
        spotify_request(
            "POST",
            f"/playlists/{playlist_id}/items",
            {"uris": uris[i : i + 100]},
        )


def create_playlist_flow(name, description, is_public, tracks, existing_playlist=""):
    if existing_playlist.strip():
        playlist_id = get_playlist_id(existing_playlist)
        current_uris = get_playlist_track_uris(playlist_id)
        new_tracks = [track for track in tracks if track["uri"] not in current_uris]
        playlist = spotify_request("GET", f"/playlists/{playlist_id}?fields=id,external_urls")
        add_tracks_to_playlist(playlist_id, new_tracks)
        return {
            "playlistUrl": playlist["external_urls"]["spotify"],
            "playlistId": playlist_id,
            "adicionadas": new_tracks,
            "duplicadas": len(tracks) - len(new_tracks),
        }

    playlist = spotify_request(
        "POST",
        "/me/playlists",
        {"name": name, "description": description, "public": is_public},
    )
    add_tracks_to_playlist(playlist["id"], tracks)

    return {
        "playlistUrl": playlist["external_urls"]["spotify"],
        "playlistId": playlist["id"],
        "adicionadas": tracks,
        "duplicadas": 0,
    }


def parse_songs(text):
        songs = []
        for line in text.splitlines():
                value = line.strip()
                value = value.lstrip("-*0123456789.) ").strip()
                if value and not value.startswith(("#", "Playlist:", "Playlist -")):
                        songs.append(value)
        return list(dict.fromkeys(songs))


PAGE = r'''<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Playlist Studio</title>
    <style>
        :root { --ink:#17221d; --muted:#68746d; --paper:#f5f2ea; --card:#fffdf8; --green:#1ed760; --line:#dce2d9; --red:#c95d4b; }
        * { box-sizing:border-box; } body { margin:0; color:var(--ink); background:var(--paper); font-family: Georgia, 'Times New Roman', serif; }
        body:before { content:''; position:fixed; inset:0; pointer-events:none; opacity:.22; background-image:radial-gradient(#9dac9e 1px, transparent 1px); background-size:22px 22px; }
        main { width:min(1080px, calc(100% - 36px)); margin:0 auto; padding:42px 0 70px; position:relative; }
        header { display:flex; align-items:flex-end; justify-content:space-between; gap:20px; margin-bottom:38px; }
        .eyebrow { font:700 12px/1.2 Arial,sans-serif; letter-spacing:.16em; text-transform:uppercase; color:#4c7657; }
        h1 { font-size:clamp(42px, 7vw, 78px); line-height:.88; letter-spacing:-.04em; margin:12px 0 0; max-width:650px; font-weight:500; }
        .badge { border:1px solid var(--line); background:var(--card); padding:10px 14px; font:700 12px Arial,sans-serif; border-radius:30px; white-space:nowrap; }
        .dot { display:inline-block; width:8px; height:8px; background:var(--green); border-radius:50%; margin-right:7px; }
        .layout { display:grid; grid-template-columns:minmax(0, 1.05fr) minmax(320px, .95fr); gap:24px; }
        section { background:var(--card); border:1px solid var(--line); padding:26px; box-shadow:8px 8px 0 #e7e3d8; }
        label { display:block; font:700 12px Arial,sans-serif; text-transform:uppercase; letter-spacing:.1em; margin-bottom:9px; }
        input, textarea, select { width:100%; border:1px solid var(--line); background:#fff; color:var(--ink); padding:14px; font:18px Georgia,serif; outline:none; }
        input:focus, textarea:focus, select:focus { border-color:#6c9b78; box-shadow:0 0 0 3px #dcefe0; }
        textarea { min-height:285px; resize:vertical; line-height:1.5; }
        .field { margin-bottom:20px; } .hint { color:var(--muted); font:13px/1.4 Arial,sans-serif; margin:8px 0 0; }
        button { border:0; cursor:pointer; padding:15px 20px; font:700 13px Arial,sans-serif; letter-spacing:.04em; text-transform:uppercase; }
        .primary { background:var(--green); color:#092612; width:100%; } .primary:hover { background:#62e58b; }
        .secondary { background:#edf2eb; color:var(--ink); margin-top:10px; width:100%; } button:disabled { opacity:.55; cursor:wait; }
        .results-head { display:flex; justify-content:space-between; align-items:start; border-bottom:1px solid var(--line); padding-bottom:18px; margin-bottom:4px; }
        h2 { font-size:28px; font-weight:500; margin:0; } .count { font:12px Arial,sans-serif; color:var(--muted); text-align:right; }
        .track { display:flex; gap:12px; align-items:center; padding:15px 0; border-bottom:1px solid #edf0ea; }
        .status { width:23px; height:23px; border-radius:50%; display:grid; place-items:center; color:white; font:700 13px Arial,sans-serif; background:#3a9d5d; flex:none; }
        .missing .status { background:var(--red); } .track strong { display:block; font-size:17px; font-weight:500; } .track small { color:var(--muted); font:13px Arial,sans-serif; } .track-info { flex:1; min-width:0; } .remove { background:transparent; color:var(--red); padding:7px; margin-left:auto; font-size:18px; line-height:1; text-transform:none; } .remove:hover { background:#fff0ec; }
        .empty { color:var(--muted); font:15px Arial,sans-serif; padding:45px 0; text-align:center; }
        .message { display:none; margin:16px 0 0; padding:12px; font:13px/1.4 Arial,sans-serif; background:#fff3d8; } .message.show { display:block; }
        @media (max-width:760px) { main { padding-top:25px; } header { display:block; } .badge { display:inline-block; margin-top:22px; } .layout { grid-template-columns:1fr; } section { padding:20px; } }
    </style>
</head>
<body><main>
    <header><div><div class="eyebrow">Spotify / Playlist Studio</div><h1>Transforme uma ideia em playlist.</h1></div><div class="badge"><span class="dot"></span>fluxo local seguro</div></header>
    <div class="layout">
        <section>
            <div class="field"><label for="name">Nome da playlist</label><input id="name" value="Escolha um nome para sua playlist></div>
            <div class="field"><label for="existing">Playlist existente (opcional)</label><select id="playlistSelect"><option value="">Carregar minhas playlists...</option></select><input id="existing" placeholder="Ou cole a URL ou o ID para adicionar sem duplicar"><p class="hint">Escolha uma playlist da sua conta ou cole uma URL. Deixe vazio para criar uma nova.</p></div>
            <div class="field"><label for="prompt">Peça uma playlist à IA</label><textarea id="prompt" class="prompt" placeholder="Ex.: gere uma lista com 15 raps de Portugal mais famosos"></textarea><button class="secondary" id="generate">Gerar com IA</button><p class="hint">A IA sugere as músicas; o Spotify confirma quais existem.</p></div>
            <div class="field"><label for="songs">Cole as músicas</label><textarea id="songs" placeholder="Piruka - Se Eu Não Acordar Amanhã&#10;Plutonio - Somos Iguais&#10;Slow J - Teu Eternamente"></textarea><p class="hint">Uma música por linha. O sistema pesquisa cada faixa no Spotify.</p></div>
            <button class="primary" id="search">Pesquisar músicas</button><div class="message" id="message"></div>
        </section>
        <section><div class="results-head"><h2>Celecione as Musicas Desejadas</h2><div class="count" id="count">aguardando sua lista</div></div><div id="results" class="empty">Sua seleção aparecerá aqui.</div><button class="primary" id="create" disabled>Criar no Spotify</button><button class="secondary" id="login">Conectar Spotify</button></section>
    </div>
</main>
<script>
const $ = id => document.getElementById(id); let preview = null;
function message(text) { $('message').textContent = text; $('message').classList.add('show'); }
function render(data) { preview = data; const ok = data.adicionadas || []; const bad = data.naoEncontradas || []; $('count').textContent = `${ok.length} selecionadas / ${bad.length} não encontradas`; $('results').className = ''; $('results').innerHTML = [...ok.map((t, index) => `<div class="track"><span class="status">✓</span><div class="track-info"><strong>${escapeHtml(t.nome)}</strong><small>${escapeHtml(t.artista)}</small></div><button class="remove" title="Excluir da prévia" aria-label="Excluir ${escapeHtml(t.nome)}" onclick="removeTrack(${index})">×</button></div>`), ...bad.map(t => `<div class="track missing"><span class="status">×</span><div class="track-info"><strong>${escapeHtml(t)}</strong><small>Música não encontrada</small></div></div>`)].join('') || '<div class="empty">Nenhuma música selecionada.</div>'; $('create').disabled = !ok.length; $('create').textContent = $('existing').value.trim() ? 'Adicionar sem duplicar' : 'Criar no Spotify'; }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;', '"':'&quot;'}[c])); }
function removeTrack(index) { const removed = preview.adicionadas.splice(index, 1)[0]; render(preview); if (removed) message(`"${removed.nome}" foi removida da prévia.`); }
$('login').onclick = () => { localStorage.setItem('playlistName', $('name').value); localStorage.setItem('playlistSongs', $('songs').value); localStorage.setItem('playlistExisting', $('existing').value); location.href = '/login'; };
$('playlistSelect').onchange = () => { $('existing').value = $('playlistSelect').value; $('create').textContent = $('existing').value.trim() ? 'Adicionar sem duplicar' : 'Criar no Spotify'; };
async function loadPlaylists() { try { const r = await fetch('/playlists'); const data = await r.json(); if (!r.ok) throw Error(data.error); $('playlistSelect').innerHTML = '<option value="">Criar uma nova playlist</option>' + data.playlists.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)} (${p.tracks} músicas)</option>`).join(''); } catch(e) { $('playlistSelect').innerHTML = '<option value="">Conecte o Spotify para carregar playlists</option>'; } }
$('generate').onclick = async () => { const prompt = $('prompt').value.trim(); if (!prompt) return message('Escreva o tipo de playlist que você quer gerar.'); $('generate').disabled = true; $('message').classList.remove('show'); try { const r = await fetch('/generate-playlist', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({prompt})}); const data = await r.json(); if (!r.ok) throw Error(data.error); $('name').value = data.name; $('songs').value = data.songs.join('\n'); message(`${data.songs.length} músicas geradas. Conferindo no Spotify...`); $('search').click(); } catch(e) { message(e.message); } finally { $('generate').disabled = false; } };
$('search').onclick = async () => { const songs = $('songs').value.trim(); if (!songs) return message('Cole pelo menos uma música para pesquisar.'); $('search').disabled = true; $('message').classList.remove('show'); try { const r = await fetch('/preview', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({songs})}); const data = await r.json(); if (r.status === 401) return message('Conecte sua conta Spotify para pesquisar as músicas.'); if (!r.ok) throw Error(data.error); render(data); } catch(e) { message(e.message); } finally { $('search').disabled = false; } };
$('create').onclick = async () => { if (!preview || !preview.adicionadas.length) return; $('create').disabled = true; try { const r = await fetch('/create-playlist', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:$('name').value.trim(), existingPlaylist:$('existing').value.trim(), songs:preview.adicionadas})}); const data = await r.json(); if (!r.ok) throw Error(data.error); $('create').textContent = $('existing').value.trim() ? 'Músicas adicionadas' : 'Playlist criada'; message(data.duplicadas ? `${data.duplicadas} música(s) já estavam na playlist. ${data.adicionadas.length} adicionada(s).` : 'Tudo certo! Abrindo sua playlist no Spotify.'); window.open(data.playlistUrl, '_blank'); } catch(e) { message(e.message); $('create').disabled = false; } };
const savedName = localStorage.getItem('playlistName'), savedSongs = localStorage.getItem('playlistSongs'), savedExisting = localStorage.getItem('playlistExisting'); if (savedName) $('name').value = savedName; if (savedSongs) $('songs').value = savedSongs; if (savedExisting) $('existing').value = savedExisting; if (savedName || savedSongs || savedExisting) { localStorage.removeItem('playlistName'); localStorage.removeItem('playlistSongs'); localStorage.removeItem('playlistExisting'); }
loadPlaylists();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/":
            self._send_html(200, PAGE)

        elif parsed.path == "/playlists":
            try:
                self._send_json(200, {"playlists": get_user_playlists()})
            except RuntimeError as e:
                status = 401 if "Nao autenticado" in str(e) else 500
                self._send_json(status, {"error": str(e)})

        elif parsed.path == "/login":
            params = urllib.parse.urlencode(
                {
                    "client_id": config.CLIENT_ID,
                    "response_type": "code",
                    "redirect_uri": config.REDIRECT_URI,
                    "scope": SCOPES,
                    "state": "state123",
                }
            )
            self.send_response(302)
            self.send_header("Location", f"{SPOTIFY_AUTH_URL}?{params}")
            self.end_headers()

        elif parsed.path == "/callback":
            qs = urllib.parse.parse_qs(parsed.query)
            if "error" in qs:
                self._send_html(400, f"Erro na autorizacao: {qs['error'][0]}")
                return
            code = qs.get("code", [None])[0]
            if not code:
                self._send_html(400, "Codigo de autorizacao ausente.")
                return
            try:
                auth_header = base64.b64encode(
                    f"{config.CLIENT_ID}:{config.CLIENT_SECRET}".encode()
                ).decode()
                data = urllib.parse.urlencode(
                    {
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": config.REDIRECT_URI,
                    }
                ).encode()
                req = urllib.request.Request(SPOTIFY_TOKEN_URL, data=data, method="POST")
                req.add_header("Authorization", f"Basic {auth_header}")
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
                with urllib.request.urlopen(req) as resp:
                    payload = json.loads(resp.read())
                tokens["access_token"] = payload["access_token"]
                tokens["refresh_token"] = payload["refresh_token"]
                tokens["expires_at"] = time.time() + payload["expires_in"]
                self.send_response(302)
                self.send_header("Location", "/?authorized=1")
                self.end_headers()
            except Exception as e:
                self._send_html(500, f"Erro ao trocar o codigo por token: {e}")

        else:
            self._send_html(404, "Rota nao encontrada.")

    def do_POST(self):
        if self.path not in ("/generate-playlist", "/preview", "/create-playlist"):
            self._send_json(404, {"error": "Rota nao encontrada."})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "JSON invalido no corpo da requisicao."})
            return

        if self.path == "/generate-playlist":
            prompt = body.get("prompt", "").strip()
            if not prompt:
                self._send_json(400, {"error": "Envie o pedido da playlist."})
                return
            try:
                self._send_json(200, generate_playlist_request(prompt))
            except RuntimeError as error:
                self._send_json(503, {"error": str(error)})
            return

        if self.path == "/preview":
            songs = parse_songs(body.get("songs", ""))
            if not songs:
                self._send_json(400, {"error": "Envie pelo menos uma musica."})
                return
            try:
                encontradas, nao_encontradas = search_tracks(songs)
                self._send_json(
                    200,
                    {
                        "adicionadas": encontradas,
                        "naoEncontradas": nao_encontradas,
                    },
                )
            except RuntimeError as e:
                if "Nao autenticado" in str(e):
                    self._send_json(401, {"error": "Autenticacao necessaria."})
                else:
                    self._send_json(500, {"error": str(e)})
            return

        name = body.get("name")
        tracks = body.get("songs")
        existing_playlist = body.get("existingPlaylist", "")
        description = body.get("description", "Criada pelo Playlist Studio")
        is_public = body.get("public", False)

        if not name or not isinstance(tracks, list) or len(tracks) == 0:
            self._send_json(
                400,
                {"error": 'Envie "name" (string) e "songs" (lista com pelo menos 1 musica).'},
            )
            return

        try:
            result = create_playlist_flow(
                name, description, is_public, tracks, existing_playlist
            )
            self._send_json(200, result)
        except Exception as e:
            print(f"[ERRO create-playlist] {e}")
            self._send_json(500, {"error": str(e)})

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", config.PORT), Handler)
    print(f"Servidor rodando em http://127.0.0.1:{config.PORT}")
    print(f"Abra http://127.0.0.1:{config.PORT}/login para autenticar.")
    server.serve_forever()