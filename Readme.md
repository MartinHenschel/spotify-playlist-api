# API de playlists do Spotify (versão Python, sem instalar nada)

Essa versão usa **só bibliotecas nativas do Python** (`http.server`, `urllib`, `json`, `base64`).
Não precisa de `pip install`, não precisa de internet pra baixar pacotes — só do Python que já
está no seu PC.

## 1. Criar o app no Spotify

1. Acesse https://developer.spotify.com/dashboard e faça login.
2. **Create app** → preencha nome/descrição.
3. Em **Redirect URI**, adicione exatamente: `http://127.0.0.1:8888/callback`
   (tem que ser `127.0.0.1`, não `localhost` — o Spotify não aceita mais `localhost`)
4. Salve e copie o **Client ID** e o **Client Secret**.

## 2. Configurar

Copie `.env.example` para `.env` e preencha seu Client ID e Client Secret:

```text
SPOTIFY_CLIENT_ID=seu_client_id_aqui
SPOTIFY_CLIENT_SECRET=seu_client_secret_aqui
```

O arquivo `.env` nao deve ser publicado no GitHub.

## 3. Rodar

No terminal, dentro da pasta do projeto:

```
python server.py
```

(se `python` não funcionar, tente `python3` ou `py`)

Deve aparecer:

```
Servidor rodando em http://127.0.0.1:8888
```

## 4. Autenticar

Abra no navegador: `http://127.0.0.1:8888/login`

Faça login e autorize. Você verá "Autenticado com sucesso!". **Repita esse passo toda vez que
reiniciar o script**, já que o token fica só na memória.

## 5. Usar a interface

Abra `http://127.0.0.1:8888`. Depois de conectar o Spotify, suas playlists aparecem no seletor.
Cole as musicas, pesquise e clique em **Criar no Spotify**. Se escolher uma playlist existente,
o sistema adiciona somente as musicas que ainda nao estao nela.

## 6. Criar a playlist pela API

Com o servidor rodando, envie um POST. Se você tiver `curl` disponível:

```
curl -X POST http://127.0.0.1:8888/create-playlist -H "Content-Type: application/json" -d "{\"name\": \"Minha Playlist\", \"songs\": [\"Legiao Urbana - Tempo Perdido\", \"Djavan - Oceano\"]}"
```

Se não tiver `curl` no PowerShell, use este comando alternativo (Invoke-RestMethod, nativo do
Windows):

```powershell
$body = @{
    name = "Minha Playlist"
    description = "Criada via API"
    public = $false
    songs = @("Legiao Urbana - Tempo Perdido", "Djavan - Oceano")
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8888/create-playlist" -Method Post -Body $body -ContentType "application/json; charset=utf-8"
```

### Resposta esperada

```json
{
  "playlistUrl": "https://open.spotify.com/playlist/xxxxx",
  "playlistId": "xxxxx",
  "adicionadas": [
    { "query": "Legiao Urbana - Tempo Perdido", "nome": "Tempo Perdido", "artista": "Legião Urbana", "uri": "spotify:track:..." }
  ],
  "naoEncontradas": []
}
```

## Se der erro de proxy da empresa

Redes corporativas às vezes bloqueiam conexões HTTPS de saída não autorizadas. Se aparecer erro
de conexão ao chamar a API do Spotify (e não um erro de autenticação), pode ser bloqueio de rede —
nesse caso, fale com o TI ou teste em uma rede sem restrição (ex: celular como hotspot) pra
confirmar se é isso mesmo.
