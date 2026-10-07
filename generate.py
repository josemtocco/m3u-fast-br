#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de lista M3U para SS IPTV.

Monta uma lista .m3u combinando canais FAST (gratuitos) brasileiros:
Pluto TV BR e Runtime.tv. Tambem aceita qualquer fonte M3U externa
(type: m3u), para o caso de voce encontrar outro feed BR.

Streams:
  - Pluto TV: URL HLS oficial do stitcher da propria Pluto TV, montada a
    partir de uma sessao anonima iniciada em boot.pluto.tv (mesmo mecanismo
    do site https://pluto.tv/br/watch/live-tv/). Os metadados (nome, logo,
    grupo, numero, EPG) vem do projeto open-source matthuisman/i.mjh.nz.
  - Runtime.tv: canais lineares da API oficial (plataforma OTTera), com o
    stream HLS oficial ja embutido.

Uso:
    python generate.py --config config.yml
"""
import argparse
import gzip
import json
import os
import re
import sys
import time
import uuid
import datetime
from urllib.parse import urlparse, parse_qs, urlencode

import requests
import yaml

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
MJH = "https://github.com/matthuisman/i.mjh.nz/raw/refs/heads/master"
EXTINF_RE = re.compile(r'^#EXTINF:(-?\d+)\s*(.*?),(.*)$')
ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')


# --------------------------------------------------------------------------
# Download helpers
# --------------------------------------------------------------------------
def http_get(url, timeout=60, retries=3):
    headers = {"User-Agent": USER_AGENT}
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep((attempt + 1) * 5)
                continue
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1 + attempt)
    print(f"  [AVISO] falha ao baixar {url}: {last}", file=sys.stderr)
    return None


def get_json_gz(url):
    r = http_get(url)
    if not r:
        return None
    try:
        return json.loads(gzip.decompress(r.content))
    except OSError:
        return json.loads(r.content.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  [AVISO] JSON invalido em {url}: {exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------
# Channel container
# --------------------------------------------------------------------------
class Channel:
    __slots__ = ("cid", "name", "logo", "chno", "group", "url")

    def __init__(self, cid, name, url, logo="", chno=None, group=""):
        self.cid = cid
        self.name = name
        self.url = url
        self.logo = logo or ""
        self.chno = chno
        self.group = group or ""

    @property
    def key(self):
        return self.url.strip() or (self.cid, self.name)

    def render(self, group):
        # tvg-name = identificador de guia usado pelo SS IPTV (ele casa o EPG
        # pelo tvg-name, nao pelo tvg-id). Para a Pluto, o id do canal e o
        # mesmo usado no XMLTV do matthuisman, entao o guia bate certo.
        epg_id = self.cid or self.name
        attrs = [
            f'tvg-id="{self.cid}"',
            f'tvg-name="{epg_id}"',
        ]
        if self.chno is not None:
            attrs.append(f'tvg-chno="{self.chno}"')
        if self.logo:
            attrs.append(f'tvg-logo="{self.logo}"')
        attrs.append(f'group-title="{group}"')
        return f"#EXTINF:-1 {' '.join(attrs)},{self.name}\n{self.url}"


# --------------------------------------------------------------------------
# Provedores nativos
# --------------------------------------------------------------------------
# Playlists da Pluto TV ja geradas a partir de um IP brasileiro (com token de
# regiao BR valido). Montar o token aqui nao funcionaria, porque o GitHub
# Actions roda nos EUA e a Pluto fixa a regiao pelo IP de quem gera o link --
# resultando na tela de "canal indisponivel". Por isso reaproveitamos uma fonte
# publica que ja publica os links com token BR, atualizada varias vezes ao dia.
PLUTO_LIVE_BASE = (
    "https://raw.githubusercontent.com/OwnerPlugins/pluto-tv-m3u/main/"
    "pluto-live-{cc}.m3u"
)
# region (i.mjh.nz) -> codigo de pais (ISO) da fonte acima
PLUTO_REGION_CC = {
    "br": "BR", "us": "US", "mx": "MX", "ar": "AR", "cl": "CL",
    "co": "CO", "es": "ES", "de": "DE", "fr": "FR", "gb": "GB",
    "it": "IT", "ca": "CA", "pe": "PE", "uy": "UY", "ve": "VE",
}


def provider_pluto(regions):
    """Canais ao vivo da Pluto TV com link HLS oficial e token de regiao BR.

    Em vez de gerar o token aqui (o que daria regiao errada, pois rodamos fora
    do Brasil), baixamos a playlist ja pronta -- com token BR valido -- de uma
    fonte publica atualizada varias vezes ao dia. O EPG (guia) vem da fonte
    open-source `matthuisman/i.mjh.nz`.
    """
    out, epg = [], []
    for region in regions:
        cc = PLUTO_REGION_CC.get(region.lower(), region.upper())
        url = PLUTO_LIVE_BASE.format(cc=cc)
        r = http_get(url)
        if not r:
            print(f"  [AVISO] Pluto TV: nao consegui baixar a lista de '{cc}'")
            continue
        epg.append(f"{MJH}/PlutoTV/{region}.xml.gz")
        pending = None
        for line in r.text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#EXTINF"):
                m = EXTINF_RE.match(line)
                if m:
                    attrs = dict(ATTR_RE.findall(m.group(2)))
                    pending = (attrs, m.group(3).strip())
            elif line.startswith("#"):
                continue
            elif pending is not None:
                attrs, title = pending
                out.append(Channel(
                    attrs.get("tvg-id", ""),
                    title or attrs.get("tvg-name", ""),
                    line,
                    attrs.get("tvg-logo", ""),
                    attrs.get("tvg-chno"),
                    attrs.get("group-title", ""),
                ))
                pending = None
    return out, epg


def provider_runtime(language="pt", country="BR"):
    """Canais lineares (FAST) oficiais da Runtime.tv (plataforma OTTera).

    A Runtime.tv roda na OTTera. A lista de canais lineares vem do endpoint
    publico `search` da API da OTTera; o acesso usa o par de cabecalhos de
    autorizacao do proprio site (token `ottera-cs-auth` + `ottera-referrer`),
    exatamente como o player web faz. Cada canal ja traz um `video_url` HLS
    (.m3u8) pronto para tocar, entao o stream oficial e embutido direto na
    lista (sem redirecionador).
    """
    base = "https://api-ott.runtime.tv"
    headers = {
        "User-Agent": USER_AGENT,
        "ottera-cs-auth": "yhCZviqLb7pvesmf22YPBkGWzXp",
        "ottera-referrer": "runtime.tv",
    }
    params = {
        "object_type": "video",
        "video_type": "linear",
        "max": "500",
        "language": language or "pt",
    }
    if country:
        params["force_country_code"] = country
    out, epg = [], []
    try:
        r = requests.get(base + "/search", headers=headers,
                         params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  [AVISO] Runtime.tv: falha na API: {exc}", file=sys.stderr)
        return out, epg
    for o in data.get("objects", []):
        url = o.get("video_url") or ""
        if not url.startswith("http"):
            continue
        if "video_not_available" in url or "placeholder" in url:
            continue  # canal temporariamente indisponivel
        # Usamos a URL de stream OFICIAL COMPLETA da Runtime -- exatamente a
        # mesma que o player do site runtime.tv usa (com os parametros de
        # app/dispositivo). Nao removemos parametros: o servidor de anuncios
        # da OTTera precisa deles para decidir corretamente o stream por pais;
        # sem eles, de um IP do Brasil, o canal pode nao abrir. A URL fica
        # longa (~900 chars), mas o encurtador (TinyURL) deixa o link curto
        # para o SS IPTV, preservando a URL oficial no redirecionamento.
        cat = ""
        meta = o.get("meta") or {}
        cats = meta.get("categories") or []
        if cats:
            cat = cats[0].get("name", "")
        out.append(Channel(
            str(o.get("id", "")),
            o.get("name", o.get("id", "")),
            url,
            o.get("logo", "") or o.get("logo_poster", ""),
            None,
            cat,
        ))
    return out, epg


def _runtime_trim(url):
    """Reduz a URL da Runtime mantendo so o essencial (network_id).

    Streams via `stream.ads.ottera.tv/playlist.m3u8` tocam apenas com
    `network_id`. URLs diretas (ex.: amagi) nao tem esse parametro e sao
    devolvidas intactas (ja sao curtas).
    """
    try:
        p = urlparse(url)
        if "ottera.tv" not in p.netloc or not p.path.endswith("playlist.m3u8"):
            return url
        q = parse_qs(p.query)
        nid = q.get("network_id", [""])[0]
        if not nid:
            return url
        return f"{p.scheme}://{p.netloc}{p.path}?network_id={nid}"
    except Exception:  # noqa: BLE001
        return url


def provider_m3u(sources):
    """Fonte M3U externa generica (qualquer URL de lista .m3u/.m3u8)."""
    out = []
    for src in sources or []:
        r = http_get(src)
        if not r:
            continue
        lines = r.text.splitlines()
        pending = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#EXTINF"):
                m = EXTINF_RE.match(line)
                if m:
                    attrs = dict(ATTR_RE.findall(m.group(2)))
                    pending = (attrs, m.group(3).strip())
            elif line.startswith("#"):
                continue
            elif pending is not None:
                attrs, title = pending
                out.append(Channel(
                    attrs.get("tvg-id", ""), title, line,
                    attrs.get("tvg-logo", ""), attrs.get("tvg-chno"),
                    attrs.get("group-title", ""),
                ))
                pending = None
    return out, []


PROVIDERS = {
    "pluto": provider_pluto,
}


# --------------------------------------------------------------------------
# Filtros + escrita
# --------------------------------------------------------------------------
def matches(name, terms):
    low = name.lower()
    return any(t.lower() in low for t in terms if t)


def apply_filters(channels, inc, exc, g_inc, g_exc):
    res = []
    for ch in channels:
        if g_inc and not matches(ch.name, g_inc):
            continue
        if g_exc and matches(ch.name, g_exc):
            continue
        if inc and not matches(ch.name, inc):
            continue
        if exc and matches(ch.name, exc):
            continue
        res.append(ch)
    return res


def write_m3u(path, items, epg_attr=None):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = "#EXTM3U"
    if epg_attr:
        header += f' url-tvg="{epg_attr}"'
    # IMPORTANTE p/ SS IPTV: nada de linha de comentario entre o #EXTM3U e o
    # primeiro par #EXTINF/URL -- o parser do SS IPTV pode travar. A data de
    # geracao vai como atributo no proprio cabecalho (ignorado por quem nao usa).
    header += f' x-generated="{now}"'
    out = [header]
    for group, ch in items:
        out.append(ch.render(group))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# --------------------------------------------------------------------------
# Encurtador de URL (TinyURL) para links muito longos (ex.: Pluto TV)
# --------------------------------------------------------------------------
_SHORT_CACHE = {}


def shorten_url(url, min_len=500, retries=4):
    """Encurta uma URL longa via TinyURL (sem necessidade de chave de API).

    So encurta URLs acima de `min_len` -- URLs ja curtas (Runtime, streams
    diretos) sao devolvidas intactas. O TinyURL devolve um link curto
    (~28 chars) que redireciona (301) para a URL original; players como VLC
    e SS IPTV seguem o redirecionamento normalmente. Em caso de falha de
    rede/limite, a URL original e mantida (nunca quebra a lista).
    """
    if not url or len(url) <= min_len or not url.startswith("http"):
        return url
    if url in _SHORT_CACHE:
        return _SHORT_CACHE[url]
    api = "https://tinyurl.com/api-create.php?url=" + requests.utils.quote(
        url, safe="")
    for attempt in range(retries):
        try:
            r = requests.get(api, timeout=30)
            txt = (r.text or "").strip()
            if r.status_code == 200 and txt.startswith("http") \
                    and "error" not in txt.lower():
                _SHORT_CACHE[url] = txt
                time.sleep(0.3)  # educado com o servico
                return txt
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1 + attempt * 2)
    print("  [AVISO] nao consegui encurtar uma URL; mantendo a original",
          file=sys.stderr)
    return url


def main():
    ap = argparse.ArgumentParser(description="Gera lista M3U para SS IPTV")
    ap.add_argument("--config", default="config.yml")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    output_file = cfg.get("output_file", "playlists/lista.m3u")
    per_provider = cfg.get("generate_per_provider", True)
    do_shorten = cfg.get("shorten_urls", True)
    shorten_min = int(cfg.get("shorten_min_len", 500))
    gf = cfg.get("global_filters", {}) or {}
    g_inc = gf.get("include") or []
    g_exc = gf.get("exclude") or []

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

    seen = set()
    combined = []
    epg_all = []
    report = []

    for prov in cfg.get("providers", []):
        if not prov.get("enabled", True):
            continue
        name = prov.get("name", "Provedor")
        group = prov.get("group", name)
        ptype = prov.get("type", "")
        regions = prov.get("regions") or []
        print(f"==> {name} ({ptype})")

        if ptype in PROVIDERS:
            channels, epg = PROVIDERS[ptype](regions)
        elif ptype == "m3u":
            channels, epg = provider_m3u(prov.get("sources"))
        elif ptype in ("runtime", "ottera"):
            channels, epg = provider_runtime(
                prov.get("language", "pt"),
                prov.get("country", "BR"),
            )
        else:
            print(f"  [AVISO] tipo desconhecido: {ptype}")
            continue

        channels = apply_filters(
            channels, prov.get("include") or [], prov.get("exclude") or [],
            g_inc, g_exc,
        )

        unique = []
        for ch in channels:
            if ch.key in seen:
                continue
            seen.add(ch.key)
            unique.append(ch)

        if do_shorten and unique:
            n_long = sum(1 for c in unique if len(c.url) > shorten_min)
            if n_long:
                print(f"  encurtando {n_long} URLs longas (TinyURL)...")
                for c in unique:
                    c.url = shorten_url(c.url, min_len=shorten_min)

        combined.extend((group, ch) for ch in unique)
        epg_all.extend(epg)
        report.append((name, len(unique)))
        print(f"  {len(unique)} canais")

        if per_provider and unique:
            path = os.path.join(os.path.dirname(output_file),
                                f"{slugify(name)}.m3u")
            write_m3u(path, [(group, c) for c in unique],
                      ",".join(dict.fromkeys(epg)))
            print(f"  gravado {path}")

    write_m3u(output_file, combined, ",".join(dict.fromkeys(epg_all)))

    print("\n==== RESUMO ====")
    for name, n in report:
        print(f"  {name}: {n} canais")
    print(f"  TOTAL: {len(combined)} canais")
    print(f"  Arquivo: {output_file}")


if __name__ == "__main__":
    main()
