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
        attrs = [f'tvg-id="{self.cid}"']
        if self.chno is not None:
            attrs.append(f'tvg-chno="{self.chno}"')
        if self.logo:
            attrs.append(f'tvg-logo="{self.logo}"')
        attrs.append(f'group-title="{group}"')
        return f"#EXTINF:-1 {' '.join(attrs)},{self.name}\n{self.url}"


# --------------------------------------------------------------------------
# Provedores nativos
# --------------------------------------------------------------------------
def _pluto_session():
    """Inicia uma sessao anonima na Pluto TV e devolve os parametros do
    stitcher (necessarios para montar as URLs de stream oficiais)."""
    did = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    params = {
        "appName": "web", "appVersion": "5.0", "deviceVersion": "126",
        "deviceModel": "web", "deviceMake": "chrome", "deviceType": "web",
        "clientID": did, "clientModelNumber": "na",
        "serverSideAds": "false", "sid": sid,
        "drmCapabilities": "widevine:L3",
    }
    try:
        r = requests.get("https://boot.pluto.tv/v4/start",
                         headers={"User-Agent": USER_AGENT},
                         params=params, timeout=40)
        r.raise_for_status()
        b = r.json()
        return (
            b.get("stitcherParams", ""),
            b.get("sessionToken", ""),
            b.get("servers", {}).get(
                "stitcher",
                "https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [AVISO] Pluto TV: falha ao iniciar sessao: {exc}",
              file=sys.stderr)
        return None, None, None


def provider_pluto(regions):
    """Canais ao vivo da Pluto TV.

    A lista de canais (nome, logo, grupo, numero, EPG) de cada regiao vem da
    fonte open-source `matthuisman/i.mjh.nz`; o link de stream, porem, e a URL
    HLS **oficial da propria Pluto TV** (stitcher), montada a partir de uma
    sessao anonima iniciada em `boot.pluto.tv` -- exatamente como o site
    https://pluto.tv/br/watch/live-tv/ faz no navegador.
    """
    data = get_json_gz(f"{MJH}/PlutoTV/.channels.json.gz")
    out, epg = [], []
    if not data:
        return out, epg
    sp, tok, stitcher = _pluto_session()
    if not sp:
        return out, epg
    for region in regions:
        rdata = data.get("regions", {}).get(region)
        if not rdata:
            print(f"  [AVISO] Pluto TV nao possui a regiao '{region}'")
            continue
        epg.append(f"{MJH}/PlutoTV/{region}.xml.gz")
        for cid, ch in rdata.get("channels", {}).items():
            url = (f"{stitcher}/stitch/hls/channel/{cid}/master.m3u8"
                   f"?{sp}")
            if tok:
                url += f"&sessionToken={tok}"
            out.append(Channel(
                cid, ch.get("name", cid), url,
                ch.get("logo", ""), ch.get("chno"), ch.get("group", ""),
            ))
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
    out = [header, f"# Gerado automaticamente em {now}"]
    for group, ch in items:
        out.append(ch.render(group))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main():
    ap = argparse.ArgumentParser(description="Gera lista M3U para SS IPTV")
    ap.add_argument("--config", default="config.yml")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    output_file = cfg.get("output_file", "playlists/lista.m3u")
    per_provider = cfg.get("generate_per_provider", True)
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
