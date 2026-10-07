# Lista M3U FAST BR para SS IPTV

Projeto que **monta automaticamente uma lista `.m3u`** com canais gratuitos
(FAST) brasileiros de **Pluto TV BR** e **Runtime.tv**, pronta para usar no
**SS IPTV** e em qualquer player que aceite M3U (VLC, Kodi, TiviMate etc.).

Um workflow do GitHub Actions **busca os canais a cada 6 horas** e atualiza a
lista sozinho — sem servidor e sem custo.

## Provedores incluidos

| Provedor | Grupo na lista | Brasil? |
|---|---|---|
| Pluto TV | `Pluto TV BR` | **Sim** — feed `br` dedicado (~179 canais em portugues) |
| Runtime.tv | `Runtime.tv` | **Sim** — catalogo BR em portugues (~22 canais lineares) |

> **Sobre a Pluto TV BR:** o link de cada canal e a **URL HLS oficial da propria
> Pluto TV** (stitcher), com um **token de regiao BR valido**. Como o GitHub
> Actions roda fora do Brasil, o projeto nao gera o token aqui (daria regiao
> errada e os canais BR cairiam na tela de "canal indisponivel"); em vez disso
> ele reaproveita uma fonte publica que ja publica os links **com token BR**,
> atualizada varias vezes ao dia (`OwnerPlugins/pluto-tv-m3u`). O guia (EPG)
> vem da fonte open-source `matthuisman/i.mjh.nz`. (~179 canais)
>
> **Sobre a Runtime.tv:** a lista puxa os canais lineares (FAST) **diretamente
> da API oficial da Runtime.tv** (plataforma OTTera), filtrando pelo catalogo
> em portugues/Brasil (`language: pt`, `country: BR`). Cada canal ja vem com o
> stream HLS oficial (`.m3u8`) embutido na lista.
>
> Caso encontre outro feed `.m3u` BR gratuito, basta adicionar um bloco
> `type: m3u` no `config.yml` (ja ha um exemplo pronto).

## Como funciona

1. O script [`generate.py`](generate.py) le o [`config.yml`](config.yml).
2. Para cada provedor, busca a lista de canais na fonte adequada:
   - **Pluto TV BR**: links HLS oficiais **com token de regiao BR** de uma
     fonte publica atualizada varias vezes ao dia (`OwnerPlugins/pluto-tv-m3u`),
     e o guia (EPG) da fonte open-source `matthuisman/i.mjh.nz`;
   - **Runtime.tv**: canais lineares direto da API oficial da plataforma, ja
     com o stream HLS (`.m3u8`) oficial embutido.
3. Aplica filtros, remove duplicados, **encurta as URLs longas** e grava:
   - `playlists/lista.m3u` — **lista combinada** (todos os provedores);
   - `playlists/pluto-tv-br.m3u`, `playlists/runtime-tv.m3u` — uma por provedor.
4. O GitHub Actions roda esse processo **a cada 6 horas** e faz commit da lista.

## Como usar (passo a passo)

### 1. Suba o projeto no GitHub

```bash
git init
git add .
git commit -m "primeiro commit"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/SEU_REPO.git
git push -u origin main
```

### 2. Habilite as permissoes do Actions

No repositorio: **Settings -> Actions -> General -> Workflow permissions** ->
marque **Read and write permissions** -> **Save**.
Isso permite que o robo faca commit da lista atualizada.

### 3. Gere a primeira lista

Va em **Actions -> "Atualizar lista M3U" -> Run workflow**.
Ao terminar, os arquivos aparecem na pasta `playlists/`.

### 4. Pegue o link RAW e coloque no SS IPTV

O link da sua lista combinada sera:

```
https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/main/playlists/lista.m3u
```

No **SS IPTV**:

1. Abra o app e va em **Configuracoes (Settings)**.
2. Aba **Listas de reproducao / Content -> Playlists**.
3. Clique em **Adicionar**, de um nome e cole o link RAW acima.
4. Salve e volte para a tela inicial — os canais aparecem em **Minha lista**.

> A lista inclui `url-tvg` com os guias de programacao (EPG) de cada provedor,
> entao o SS IPTV tambem pode exibir a programacao dos canais.

## URLs curtas (compativel com SS IPTV)

O SS IPTV pode falhar com links muito longos. Por isso a lista ja sai com as
URLs encurtadas:

- **Pluto TV**: o link oficial tem um token de ~2.300 caracteres. Ele e
  encurtado via **TinyURL** para ~28 caracteres (o link curto redireciona para
  o stream oficial; VLC e SS IPTV seguem o redirecionamento normalmente).
- **Runtime.tv**: a URL original (~900 caracteres, cheia de parametros de
  anuncio) e reduzida pelo proprio gerador para ~58 caracteres, mantendo so o
  essencial (`network_id`) — sem depender de encurtador externo.

Isso e controlado no `config.yml` por `shorten_urls` (ligado por padrao) e
`shorten_min_len` (so encurta URLs acima desse tamanho). Se preferir os links
diretos (sem TinyURL), basta `shorten_urls: false`.

## Rodar localmente (opcional)

```bash
pip install -r requirements.txt
python generate.py --config config.yml
```

Resultado em `playlists/lista.m3u`.

## Personalizar ([`config.yml`](config.yml))

- **Ativar/desativar** um provedor: `enabled: true|false`.
- **Mudar regiao**: edite `regions` (ex.: `regions: [br]`, `regions: [us, mx]`).
- **Filtrar por nome do canal**:
  - `include: ["news", "filmes"]` mantem apenas canais com esses termos;
  - `exclude: ["24/7", "teste"]` remove canais com esses termos.
- **Filtros globais** (`global_filters`) valem para todos os provedores.
- **Adicionar uma fonte M3U propria**: use um bloco `type: m3u` com a URL do
  feed (ha um exemplo pronto, desligado, no final do arquivo).
- **Mudar a frequencia**: edite o `cron` em
  [`.github/workflows/update-playlist.yml`](.github/workflows/update-playlist.yml).
  Ex.: `0 */6 * * *` = a cada 6 horas; `0 */3 * * *` = a cada 3 horas.

## Estrutura

```
.
|- generate.py                            # gerador da lista
|- config.yml                             # provedores, regioes e filtros
|- requirements.txt                       # dependencias Python
|- playlists/                             # listas .m3u geradas
|- .github/workflows/update-playlist.yml  # automacao a cada 6 horas
```

## Aviso legal

Este projeto **nao hospeda nem redistribui conteudo**. Ele apenas organiza
links de canais gratuitos (FAST) ja disponibilizados publicamente pelos
respectivos servicos. Use de acordo com os termos de cada provedor e com a
legislacao local.

## Creditos

- Metadados de canais e EPG (Pluto TV BR): [matthuisman/i.mjh.nz](https://github.com/matthuisman/i.mjh.nz)
- Canais lineares da Runtime.tv: API oficial da plataforma

## Licenca

[MIT](LICENSE)
