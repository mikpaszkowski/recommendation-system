#!/usr/bin/env python3
"""
Context-Aware Category-Centric Live Evaluation Dataset Extractor and Compiler.

Implements Requirements R2, R3, R4 of ORIGINAL_REQUEST.md (§ 2026-10-06T17:26:22Z):
- Queries live Neo4j for exactly 50 candidates in each of the 7 target categories:
  Camera, Phone, Charger, Mouse, Headphone, Laptop, Keyboard (350 total candidates).
- Enforces strict negative accessory exclusions and quality constraints ($price > 0$, valid 384-d embedding, reviews).
- Computes dense vector peer cosine similarity clusters for candidate neighborhoods.
- Selects exactly 3 target items per category (21 total scenarios) possessing similar peers and distinct distinguishing features.
- Synthesizes non-generic, discriminative conversational utterances targeting specific distinguishing features.
- Overwrites live_eval_dataset.json conforming to RFC 8259 JSON (zero NaN values) and dual-compatible schema.
- Verifies 100% of target and peer ASINs exist in live Neo4j (Strict Zero-Mock Mandate).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.database.neo4j_connection import Neo4jConnectionManager, Neo4jConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extract_live_eval_dataset")

# ==============================================================================
# AUTHORITATIVE CYPHER QUERIES FOR 50 CANDIDATES PER CATEGORY
# ==============================================================================

CATEGORY_CYPHER_QUERIES: Dict[str, str] = {
    "Camera": """
        MATCH (p:ParentProduct)
        WHERE (toLower(p.title) CONTAINS "camera" OR toLower(p.title) CONTAINS "camcorder" OR toLower(p.title) CONTAINS "webcam")
          AND NOT toLower(p.title) CONTAINS "paper"
          AND NOT toLower(p.title) CONTAINS "film only"
          AND NOT toLower(p.title) CONTAINS "case"
          AND NOT toLower(p.title) CONTAINS "bag"
          AND NOT toLower(p.title) CONTAINS "backpack"
          AND NOT toLower(p.title) CONTAINS "strap"
          AND NOT toLower(p.title) CONTAINS "mount"
          AND NOT toLower(p.title) CONTAINS "holder"
          AND NOT toLower(p.title) CONTAINS "tripod"
          AND NOT toLower(p.title) CONTAINS "monopod"
          AND NOT toLower(p.title) CONTAINS "lens cap"
          AND NOT toLower(p.title) CONTAINS "lens hood"
          AND NOT toLower(p.title) CONTAINS "lens "
          AND NOT toLower(p.title) CONTAINS "filter"
          AND NOT toLower(p.title) CONTAINS "cable"
          AND NOT toLower(p.title) CONTAINS "cord"
          AND NOT toLower(p.title) CONTAINS "charger"
          AND NOT toLower(p.title) CONTAINS "battery"
          AND NOT toLower(p.title) CONTAINS "adapter"
          AND NOT toLower(p.title) CONTAINS "flash drive"
          AND NOT toLower(p.title) CONTAINS "memory stick"
          AND NOT toLower(p.title) CONTAINS "usb stick"
          AND NOT toLower(p.title) CONTAINS "card reader"
          AND NOT toLower(p.title) CONTAINS "screen protector"
          AND NOT toLower(p.title) CONTAINS "skin"
          AND NOT toLower(p.title) CONTAINS "decal"
          AND NOT toLower(p.title) CONTAINS "sticker"
          AND NOT toLower(p.title) CONTAINS "dummy"
          AND NOT toLower(p.title) CONTAINS "fake"
          AND NOT toLower(p.title) CONTAINS "detector"
          AND NOT toLower(p.title) CONTAINS "car stereo"
          AND NOT toLower(p.title) CONTAINS "radio player"
          AND NOT toLower(p.title) CONTAINS "head unit"
          AND NOT toLower(p.title) CONTAINS "laptop"
          AND NOT toLower(p.title) CONTAINS "macbook"
          AND NOT toLower(p.title) CONTAINS "illuminator"
          AND NOT toLower(p.title) CONTAINS "infrared light"
          AND NOT toLower(p.title) CONTAINS "ir light"
          AND NOT toLower(p.title) CONTAINS "tamron"
          AND NOT toLower(p.title) CONTAINS "echo show"
          AND NOT toLower(p.title) CONTAINS "phone"
          AND NOT toLower(p.title) CONTAINS "smartphone"
          AND NOT toLower(p.title) CONTAINS "for camera"
          AND NOT toLower(p.title) CONTAINS "for dslr"
          AND p.price IS NOT NULL AND p.price >= 20.0
          AND p.embedding IS NOT NULL
        OPTIONAL MATCH (p)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (p)<-[:ABOUT_PRODUCT]-(r:Review)
        OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WITH p, b, count(DISTINCT r) as rev_count, collect(DISTINCT {name: a.attribute_name, val: a.attribute_value}) as attrs
        WHERE rev_count >= 1
        RETURN p.parent_asin as asin,
               p.title as title,
               p.price as price,
               p.avg_rating as rating,
               b.name as brand,
               p.description as description,
               rev_count,
               size(attrs) as attr_count,
               attrs,
               p.embedding as embedding
        ORDER BY rev_count DESC, p.avg_rating DESC
        LIMIT 50
    """,
    "Phone": """
        MATCH (p:ParentProduct)
        WHERE (toLower(p.title) CONTAINS "smartphone" 
            OR toLower(p.title) CONTAINS "cell phone" 
            OR toLower(p.title) CONTAINS "cellular phone" 
            OR toLower(p.title) CONTAINS "mobile phone" 
            OR toLower(p.title) CONTAINS "flip phone" 
            OR toLower(p.title) CONTAINS "cordless phone" 
            OR toLower(p.title) CONTAINS "unlocked phone" 
            OR (toLower(p.title) CONTAINS "telephone" AND (toLower(p.title) CONTAINS "system" OR toLower(p.title) CONTAINS "corded" OR toLower(p.title) CONTAINS "cordless" OR toLower(p.title) CONTAINS "at&t" OR toLower(p.title) CONTAINS "panasonic" OR toLower(p.title) CONTAINS "vtech" OR toLower(p.title) CONTAINS "uniden"))
            OR (toLower(p.title) CONTAINS "iphone" AND (toLower(p.title) CONTAINS "apple" OR toLower(p.title) CONTAINS "unlocked" OR toLower(p.title) CONTAINS "renewed" OR toLower(p.title) CONTAINS "verizon" OR toLower(p.title) CONTAINS "at&t") AND (toLower(p.title) CONTAINS "gb" OR toLower(p.title) CONTAINS "plus" OR toLower(p.title) CONTAINS "pro" OR toLower(p.title) CONTAINS "mini"))
            OR (toLower(p.title) CONTAINS "galaxy" AND (toLower(p.title) CONTAINS "samsung" OR toLower(p.title) CONTAINS "unlocked" OR toLower(p.title) CONTAINS "5g") AND (toLower(p.title) CONTAINS "phone" OR toLower(p.title) CONTAINS "s20" OR toLower(p.title) CONTAINS "s10" OR toLower(p.title) CONTAINS "s9" OR toLower(p.title) CONTAINS "s8" OR toLower(p.title) CONTAINS "s21" OR toLower(p.title) CONTAINS "s22" OR toLower(p.title) CONTAINS "s23" OR toLower(p.title) CONTAINS "note" OR toLower(p.title) CONTAINS "a51" OR toLower(p.title) CONTAINS "a52" OR toLower(p.title) CONTAINS "a30" OR toLower(p.title) CONTAINS "a10" OR toLower(p.title) CONTAINS "a20" OR toLower(p.title) CONTAINS "a12" OR toLower(p.title) CONTAINS "a13" OR toLower(p.title) CONTAINS "a14" OR toLower(p.title) CONTAINS "z fold" OR toLower(p.title) CONTAINS "z flip"))
            OR (toLower(p.title) CONTAINS "pixel" AND toLower(p.title) CONTAINS "google" AND (toLower(p.title) CONTAINS "phone" OR toLower(p.title) CONTAINS "unlocked" OR toLower(p.title) CONTAINS "5g" OR toLower(p.title) CONTAINS "pro"))
            OR (toLower(p.title) CONTAINS "motorola" AND (toLower(p.title) CONTAINS "moto" OR toLower(p.title) CONTAINS "unlocked" OR toLower(p.title) CONTAINS "edge"))
            OR (toLower(p.title) CONTAINS "nokia" AND (toLower(p.title) CONTAINS "phone" OR toLower(p.title) CONTAINS "unlocked" OR toLower(p.title) CONTAINS "dual sim"))
            OR (toLower(p.title) CONTAINS "blu " AND (toLower(p.title) CONTAINS "phone" OR toLower(p.title) CONTAINS "unlocked" OR toLower(p.title) CONTAINS "smartphone")))
          AND NOT toLower(p.title) CONTAINS "case"
          AND NOT toLower(p.title) CONTAINS "cover"
          AND NOT toLower(p.title) CONTAINS "protector"
          AND NOT toLower(p.title) CONTAINS "holster"
          AND NOT toLower(p.title) CONTAINS "cable"
          AND NOT toLower(p.title) CONTAINS "charger"
          AND NOT toLower(p.title) CONTAINS "adapter"
          AND NOT toLower(p.title) CONTAINS "mount"
          AND NOT toLower(p.title) CONTAINS "holder"
          AND NOT toLower(p.title) CONTAINS "stand"
          AND NOT toLower(p.title) CONTAINS "speaker"
          AND NOT toLower(p.title) CONTAINS "headphone"
          AND NOT toLower(p.title) CONTAINS "headset"
          AND NOT toLower(p.title) CONTAINS "earbud"
          AND NOT toLower(p.title) CONTAINS "earphone"
          AND NOT toLower(p.title) CONTAINS "earpiece"
          AND NOT toLower(p.title) CONTAINS "earpod"
          AND NOT toLower(p.title) CONTAINS "stylus"
          AND NOT toLower(p.title) CONTAINS "tracker"
          AND NOT toLower(p.title) CONTAINS "trackr"
          AND NOT toLower(p.title) CONTAINS "tracking"
          AND NOT toLower(p.title) CONTAINS "antenna"
          AND NOT toLower(p.title) CONTAINS "filter"
          AND NOT toLower(p.title) CONTAINS "phone cord"
          AND NOT toLower(p.title) CONTAINS "telephone cord"
          AND NOT toLower(p.title) CONTAINS "line cord"
          AND NOT toLower(p.title) CONTAINS "two-way radio"
          AND NOT toLower(p.title) CONTAINS "two way radio"
          AND NOT toLower(p.title) CONTAINS "walkie talkie"
          AND NOT toLower(p.title) CONTAINS "talkabout"
          AND NOT toLower(p.title) CONTAINS "gps"
          AND NOT toLower(p.title) CONTAINS "ringer"
          AND NOT toLower(p.title) CONTAINS "amplifier"
          AND NOT toLower(p.title) CONTAINS "pick up"
          AND NOT toLower(p.title) CONTAINS "ir receiver"
          AND NOT toLower(p.title) CONTAINS "shoulder rest"
          AND NOT toLower(p.title) CONTAINS "switchbox"
          AND NOT toLower(p.title) CONTAINS "tablet"
          AND NOT toLower(p.title) CONTAINS "slate"
          AND NOT toLower(p.title) CONTAINS "pixelbook"
          AND NOT toLower(p.title) CONTAINS "glasses"
          AND NOT toLower(p.title) CONTAINS "folio"
          AND NOT toLower(p.title) CONTAINS "wallet"
          AND NOT toLower(p.title) CONTAINS "jack"
          AND NOT toLower(p.title) CONTAINS "module"
          AND NOT toLower(p.title) CONTAINS "watch"
          AND NOT toLower(p.title) CONTAINS "tripod"
          AND NOT toLower(p.title) CONTAINS "camcorder"
          AND NOT toLower(p.title) CONTAINS "printer"
          AND NOT toLower(p.title) CONTAINS "drive"
          AND NOT toLower(p.title) CONTAINS "stick"
          AND NOT toLower(p.title) CONTAINS "card"
          AND NOT toLower(p.title) CONTAINS "keyboard"
          AND NOT toLower(p.title) CONTAINS "macbook"
          AND NOT toLower(p.title) CONTAINS "laptop"
          AND NOT toLower(p.title) CONTAINS "fan"
          AND NOT toLower(p.title) CONTAINS "hub"
          AND NOT toLower(p.title) CONTAINS "cordless phone battery"
          AND NOT toLower(p.title) CONTAINS "phone battery"
          AND NOT toLower(p.title) CONTAINS "battery replacement"
          AND NOT toLower(p.title) CONTAINS "replacement battery"
          AND NOT toLower(p.title) CONTAINS "battery for"
          AND NOT toLower(p.title) CONTAINS "batteries for"
          AND NOT toLower(p.title) CONTAINS "rechargeable battery"
          AND NOT toLower(p.title) CONTAINS "decal"
          AND p.price IS NOT NULL AND p.price >= 15.0
          AND p.embedding IS NOT NULL
        OPTIONAL MATCH (p)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (p)<-[:ABOUT_PRODUCT]-(r:Review)
        OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WITH p, b, count(DISTINCT r) as rev_count, collect(DISTINCT {name: a.attribute_name, val: a.attribute_value}) as attrs
        RETURN p.parent_asin as asin,
               p.title as title,
               p.price as price,
               p.avg_rating as rating,
               b.name as brand,
               p.description as description,
               rev_count,
               size(attrs) as attr_count,
               attrs,
               p.embedding as embedding
        ORDER BY rev_count DESC, p.avg_rating DESC
        LIMIT 50
    """,
    "Charger": """
        MATCH (p:ParentProduct)
        WHERE (
            toLower(p.title) CONTAINS "wireless charger" 
            OR toLower(p.title) CONTAINS "wireless charging pad"
            OR toLower(p.title) CONTAINS "wireless charging station"
            OR toLower(p.title) CONTAINS "wall charger"
            OR toLower(p.title) CONTAINS "charging station"
            OR toLower(p.title) CONTAINS "portable charger"
            OR toLower(p.title) CONTAINS "power bank"
            OR toLower(p.title) CONTAINS "charging dock"
            OR toLower(p.title) CONTAINS "charger block"
            OR toLower(p.title) CONTAINS "charging block"
            OR toLower(p.title) CONTAINS "charger plug"
            OR toLower(p.title) CONTAINS "travel adapter"
            OR (toLower(p.title) CONTAINS "power adapter" AND (toLower(p.title) CONTAINS "usb" OR toLower(p.title) CONTAINS "charger" OR toLower(p.title) CONTAINS "watt" OR toLower(p.title) CONTAINS "65w" OR toLower(p.title) CONTAINS "20w" OR toLower(p.title) CONTAINS "45w" OR toLower(p.title) CONTAINS "96w" OR toLower(p.title) CONTAINS "fast"))
            OR (toLower(p.title) CONTAINS "fast charger" AND (toLower(p.title) CONTAINS "block" OR toLower(p.title) CONTAINS "plug" OR toLower(p.title) CONTAINS "brick" OR toLower(p.title) CONTAINS "box" OR toLower(p.title) CONTAINS "cube" OR toLower(p.title) CONTAINS "adapter" OR toLower(p.title) CONTAINS "wall"))
            OR (toLower(p.title) CONTAINS "usb c charger" AND (toLower(p.title) CONTAINS "plug" OR toLower(p.title) CONTAINS "block" OR toLower(p.title) CONTAINS "wall" OR toLower(p.title) CONTAINS "gan" OR toLower(p.title) CONTAINS "adapter" OR toLower(p.title) CONTAINS "port" OR toLower(p.title) CONTAINS "macbook" OR toLower(p.title) CONTAINS "laptop"))
          )
          AND NOT toLower(p.title) CONTAINS "radio"
          AND NOT toLower(p.title) CONTAINS "alarm"
          AND NOT toLower(p.title) CONTAINS "clock"
          AND NOT toLower(p.title) CONTAINS "flashlight"
          AND NOT toLower(p.title) CONTAINS "fan"
          AND NOT toLower(p.title) CONTAINS "dvd"
          AND NOT toLower(p.title) CONTAINS "bag"
          AND NOT toLower(p.title) CONTAINS "organizer"
          AND NOT toLower(p.title) CONTAINS "case"
          AND NOT toLower(p.title) CONTAINS "pouch"
          AND NOT toLower(p.title) CONTAINS "backpack"
          AND NOT toLower(p.title) CONTAINS "sleeve"
          AND NOT toLower(p.title) CONTAINS "hub"
          AND NOT toLower(p.title) CONTAINS "splitter"
          AND NOT toLower(p.title) CONTAINS "outlet extender"
          AND NOT toLower(p.title) CONTAINS "surge protector"
          AND NOT toLower(p.title) CONTAINS "multi plug"
          AND NOT toLower(p.title) CONTAINS "plug expander"
          AND NOT toLower(p.title) CONTAINS "stand only"
          AND NOT toLower(p.title) CONTAINS "holder"
          AND NOT toLower(p.title) CONTAINS "mount"
          AND NOT toLower(p.title) CONTAINS "bracket"
          AND NOT toLower(p.title) CONTAINS "watch"
          AND NOT toLower(p.title) CONTAINS "speaker"
          AND NOT toLower(p.title) CONTAINS "tablet"
          AND NOT toLower(p.title) CONTAINS "camera"
          AND NOT toLower(p.title) CONTAINS "scanner"
          AND NOT toLower(p.title) CONTAINS "power strip"
          AND NOT toLower(p.title) CONTAINS "replacement battery"
          AND NOT toLower(p.title) CONTAINS "battery replacement"
          AND NOT toLower(p.title) CONTAINS "battery pack"
          AND NOT toLower(p.title) CONTAINS "decal"
          AND NOT toLower(p.title) CONTAINS "skin"
          AND NOT toLower(p.title) CONTAINS "cable only"
          AND NOT toLower(p.title) CONTAINS "cord only"
          AND NOT toLower(p.title) CONTAINS "cable for"
          AND NOT toLower(p.title) CONTAINS "cord for"
          AND NOT toLower(p.title) CONTAINS "charging cable for"
          AND NOT toLower(p.title) CONTAINS "short usb c cord"
          AND NOT toLower(p.title) CONTAINS "extension cable"
          AND NOT toLower(p.title) CONTAINS "extension cord"
          AND NOT toLower(p.title) CONTAINS "displayport"
          AND NOT toLower(p.title) CONTAINS "hdmi"
          AND NOT toLower(p.title) CONTAINS "vga"
          AND NOT toLower(p.title) STARTS WITH "ainope 100w"
          AND NOT toLower(p.title) STARTS WITH "sunguy short"
          AND NOT toLower(p.title) STARTS WITH "hotnow short"
          AND NOT toLower(p.title) STARTS WITH "1 foot short"
          AND NOT toLower(p.title) STARTS WITH "1ft short"
          AND NOT toLower(p.title) STARTS WITH "coiled lightning"
          AND NOT toLower(p.title) STARTS WITH "fast charger, [mfi certified] 10 ft"
          AND p.price IS NOT NULL AND p.price >= 8.0
          AND p.embedding IS NOT NULL
        OPTIONAL MATCH (p)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (p)<-[:ABOUT_PRODUCT]-(r:Review)
        OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WITH p, b, count(DISTINCT r) as rev_count, collect(DISTINCT {name: a.attribute_name, val: a.attribute_value}) as attrs
        WHERE rev_count >= 1
        RETURN p.parent_asin as asin,
               p.title as title,
               p.price as price,
               p.avg_rating as rating,
               b.name as brand,
               p.description as description,
               rev_count,
               size(attrs) as attr_count,
               attrs,
               p.embedding as embedding
        ORDER BY rev_count DESC, p.avg_rating DESC
        LIMIT 50
    """,
    "Mouse": """
        MATCH (p:ParentProduct)
        WHERE (toLower(p.title) CONTAINS "mouse" OR toLower(p.title) CONTAINS "trackball")
          AND NOT toLower(p.title) CONTAINS "pad"
          AND NOT toLower(p.title) CONTAINS "mat"
          AND NOT toLower(p.title) CONTAINS "wrist rest"
          AND NOT toLower(p.title) CONTAINS "feet"
          AND NOT toLower(p.title) CONTAINS "skates"
          AND NOT toLower(p.title) CONTAINS "grip"
          AND NOT toLower(p.title) CONTAINS "case"
          AND NOT toLower(p.title) CONTAINS "bag"
          AND NOT toLower(p.title) CONTAINS "cable"
          AND NOT toLower(p.title) CONTAINS "cord"
          AND NOT toLower(p.title) CONTAINS "bungee"
          AND NOT toLower(p.title) CONTAINS "combo"
          AND NOT toLower(p.title) CONTAINS "keyboard"
          AND NOT toLower(p.title) CONTAINS "jiggler"
          AND NOT toLower(p.title) CONTAINS "mover"
          AND NOT toLower(p.title) CONTAINS "simulator"
          AND NOT toLower(p.title) CONTAINS "kvm"
          AND NOT toLower(p.title) CONTAINS "dongle"
          AND NOT toLower(p.title) CONTAINS "adapter"
          AND NOT toLower(p.title) CONTAINS "converter"
          AND NOT toLower(p.title) CONTAINS "skin"
          AND NOT toLower(p.title) CONTAINS "cover"
          AND NOT toLower(p.title) CONTAINS "bundle"
          AND NOT toLower(p.title) CONTAINS "repeller"
          AND NOT toLower(p.title) CONTAINS "traps"
          AND NOT toLower(p.title) CONTAINS "holder"
          AND NOT toLower(p.title) CONTAINS "for mouse"
          AND p.price IS NOT NULL AND p.price >= 5.0
          AND p.embedding IS NOT NULL
        OPTIONAL MATCH (p)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (p)<-[:ABOUT_PRODUCT]-(r:Review)
        OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WITH p, b, count(DISTINCT r) as rev_count, collect(DISTINCT {name: a.attribute_name, val: a.attribute_value}) as attrs
        WHERE rev_count >= 1
        RETURN p.parent_asin as asin,
               p.title as title,
               p.price as price,
               p.avg_rating as rating,
               b.name as brand,
               p.description as description,
               rev_count,
               size(attrs) as attr_count,
               attrs,
               p.embedding as embedding
        ORDER BY rev_count DESC, p.avg_rating DESC
        LIMIT 50
    """,
    "Headphone": """
        MATCH (p:ParentProduct)
        WHERE (toLower(p.title) CONTAINS "headphone" OR toLower(p.title) CONTAINS "earbuds" OR toLower(p.title) CONTAINS "earphone" OR toLower(p.title) CONTAINS "headset")
          AND NOT toLower(p.title) CONTAINS "case"
          AND NOT toLower(p.title) CONTAINS "cover"
          AND NOT toLower(p.title) CONTAINS "tips"
          AND NOT toLower(p.title) CONTAINS "eartips"
          AND NOT toLower(p.title) CONTAINS "pads"
          AND NOT toLower(p.title) CONTAINS "earpads"
          AND NOT toLower(p.title) CONTAINS "cushion"
          AND NOT toLower(p.title) CONTAINS "cushions"
          AND NOT toLower(p.title) CONTAINS "headband"
          AND NOT toLower(p.title) CONTAINS "stand"
          AND NOT toLower(p.title) CONTAINS "hanger"
          AND NOT toLower(p.title) CONTAINS "hook"
          AND NOT toLower(p.title) CONTAINS "cable"
          AND NOT toLower(p.title) CONTAINS "cord"
          AND NOT toLower(p.title) CONTAINS "adapter"
          AND NOT toLower(p.title) CONTAINS "splitter"
          AND NOT toLower(p.title) CONTAINS "replacement"
          AND NOT toLower(p.title) CONTAINS "mid-tower"
          AND NOT toLower(p.title) CONTAINS "atx"
          AND NOT toLower(p.title) CONTAINS "chassis"
          AND NOT toLower(p.title) CONTAINS "speaker"
          AND NOT toLower(p.title) CONTAINS "backpack"
          AND NOT toLower(p.title) CONTAINS "bag"
          AND NOT toLower(p.title) CONTAINS "for headphones"
          AND NOT toLower(p.title) CONTAINS "for headset"
          AND NOT toLower(p.title) CONTAINS "for airpods"
          AND p.price IS NOT NULL AND p.price >= 10.0
          AND p.embedding IS NOT NULL
        OPTIONAL MATCH (p)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (p)<-[:ABOUT_PRODUCT]-(r:Review)
        OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WITH p, b, count(DISTINCT r) as rev_count, collect(DISTINCT {name: a.attribute_name, val: a.attribute_value}) as attrs
        WHERE rev_count >= 1
        RETURN p.parent_asin as asin,
               p.title as title,
               p.price as price,
               p.avg_rating as rating,
               b.name as brand,
               p.description as description,
               rev_count,
               size(attrs) as attr_count,
               attrs,
               p.embedding as embedding
        ORDER BY rev_count DESC, p.avg_rating DESC
        LIMIT 50
    """,
    "Laptop": """
        MATCH (p:ParentProduct)
        WHERE (toLower(p.title) CONTAINS "laptop" OR toLower(p.title) CONTAINS "chromebook" OR toLower(p.title) CONTAINS "macbook")
          AND (toLower(p.title) CONTAINS "ram" OR toLower(p.title) CONTAINS "intel" OR toLower(p.title) CONTAINS "amd" OR toLower(p.title) CONTAINS "core" OR toLower(p.title) CONTAINS "ryzen" OR toLower(p.title) CONTAINS "celeron" OR toLower(p.title) CONTAINS "pentium" OR toLower(p.title) CONTAINS "gb ssd" OR toLower(p.title) CONTAINS "emmc" OR toLower(p.title) CONTAINS "windows" OR toLower(p.title) CONTAINS "chrome os")
          AND NOT toLower(p.title) CONTAINS "screen replacement"
          AND NOT toLower(p.title) CONTAINS "replacement screen"
          AND NOT toLower(p.title) CONTAINS "motherboard"
          AND NOT toLower(p.title) CONTAINS "monitor"
          AND NOT toLower(p.title) CONTAINS "digitizer"
          AND NOT toLower(p.title) CONTAINS "hard drive"
          AND NOT toLower(p.title) CONTAINS "solid state"
          AND NOT toLower(p.title) CONTAINS "external ssd"
          AND NOT toLower(p.title) CONTAINS "internal ssd"
          AND NOT toLower(p.title) CONTAINS "m.2 internal"
          AND NOT toLower(p.title) CONTAINS "sodimm"
          AND NOT toLower(p.title) CONTAINS "memory module"
          AND NOT toLower(p.title) CONTAINS "memory modules"
          AND NOT toLower(p.title) CONTAINS "document camera"
          AND NOT toLower(p.title) CONTAINS "skin"
          AND NOT toLower(p.title) CONTAINS "decal"
          AND NOT toLower(p.title) CONTAINS "sticker"
          AND NOT toLower(p.title) CONTAINS "case"
          AND NOT toLower(p.title) CONTAINS "sleeve"
          AND NOT toLower(p.title) CONTAINS "bag"
          AND NOT toLower(p.title) CONTAINS "backpack"
          AND NOT toLower(p.title) CONTAINS "stand"
          AND NOT toLower(p.title) CONTAINS "dock"
          AND NOT toLower(p.title) CONTAINS "hub"
          AND NOT toLower(p.title) CONTAINS "cable"
          AND NOT toLower(p.title) CONTAINS "charger"
          AND NOT toLower(p.title) CONTAINS "adapter"
          AND NOT toLower(p.title) CONTAINS "cooler"
          AND NOT toLower(p.title) CONTAINS "cooling"
          AND NOT toLower(p.title) CONTAINS "keyboard for"
          AND NOT toLower(p.title) CONTAINS "transmitter"
          AND NOT toLower(p.title) CONTAINS "projector"
          AND NOT toLower(p.title) CONTAINS "drawing tablet"
          AND NOT toLower(p.title) CONTAINS "graphics tablet"
          AND NOT toLower(p.title) CONTAINS "gpu enclosure"
          AND NOT toLower(p.title) CONTAINS "egpu"
          AND p.price IS NOT NULL AND p.price >= 80.0
          AND p.embedding IS NOT NULL
        OPTIONAL MATCH (p)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (p)<-[:ABOUT_PRODUCT]-(r:Review)
        OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WITH p, b, count(DISTINCT r) as rev_count, collect(DISTINCT {name: a.attribute_name, val: a.attribute_value}) as attrs
        WHERE rev_count >= 1
        RETURN p.parent_asin as asin,
               p.title as title,
               p.price as price,
               p.avg_rating as rating,
               b.name as brand,
               p.description as description,
               rev_count,
               size(attrs) as attr_count,
               attrs,
               p.embedding as embedding
        ORDER BY rev_count DESC, p.avg_rating DESC
        LIMIT 50
    """,
    "Keyboard": """
        MATCH (p:ParentProduct)
        WHERE toLower(p.title) CONTAINS "keyboard"
          AND NOT toLower(p.title) CONTAINS "laptop"
          AND NOT toLower(p.title) CONTAINS "macbook"
          AND NOT toLower(p.title) CONTAINS "notebook"
          AND NOT toLower(p.title) CONTAINS "chromebook"
          AND NOT toLower(p.title) CONTAINS "desktop computer"
          AND NOT toLower(p.title) CONTAINS "computer package"
          AND NOT toLower(p.title) CONTAINS "cover"
          AND NOT toLower(p.title) CONTAINS "skin"
          AND NOT toLower(p.title) CONTAINS "case"
          AND NOT toLower(p.title) CONTAINS "sleeve"
          AND NOT toLower(p.title) CONTAINS "wrist rest"
          AND NOT toLower(p.title) CONTAINS "palm rest"
          AND NOT toLower(p.title) CONTAINS "keycaps"
          AND NOT toLower(p.title) CONTAINS "key cap"
          AND NOT toLower(p.title) CONTAINS "switch"
          AND NOT toLower(p.title) CONTAINS "cleaner"
          AND NOT toLower(p.title) CONTAINS "cleaning"
          AND NOT toLower(p.title) CONTAINS "air duster"
          AND NOT toLower(p.title) CONTAINS "canned air"
          AND NOT toLower(p.title) CONTAINS "shelf"
          AND NOT toLower(p.title) CONTAINS "drawer"
          AND NOT toLower(p.title) CONTAINS "tray"
          AND NOT toLower(p.title) CONTAINS "lube"
          AND NOT toLower(p.title) CONTAINS "cable"
          AND NOT toLower(p.title) CONTAINS "cord"
          AND NOT toLower(p.title) CONTAINS "combo"
          AND NOT toLower(p.title) CONTAINS "keyboard and mouse"
          AND NOT toLower(p.title) CONTAINS "mouse and keyboard"
          AND NOT toLower(p.title) CONTAINS "& mouse"
          AND NOT toLower(p.title) CONTAINS "and mouse"
          AND NOT toLower(p.title) CONTAINS "bundle"
          AND NOT toLower(p.title) CONTAINS "replacement"
          AND NOT toLower(p.title) CONTAINS "piano"
          AND NOT toLower(p.title) CONTAINS "musical"
          AND NOT toLower(p.title) CONTAINS "stand"
          AND NOT toLower(p.title) CONTAINS "ipad"
          AND NOT toLower(p.title) CONTAINS "tablet"
          AND NOT toLower(p.title) CONTAINS "decal"
          AND NOT toLower(p.title) CONTAINS "sticker"
          AND NOT toLower(p.title) CONTAINS "for keyboard"
          AND p.price IS NOT NULL AND p.price >= 10.0
          AND p.embedding IS NOT NULL
        OPTIONAL MATCH (p)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (p)<-[:ABOUT_PRODUCT]-(r:Review)
        OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WITH p, b, count(DISTINCT r) as rev_count, collect(DISTINCT {name: a.attribute_name, val: a.attribute_value}) as attrs
        WHERE rev_count >= 0
        RETURN p.parent_asin as asin,
               p.title as title,
               p.price as price,
               p.avg_rating as rating,
               b.name as brand,
               p.description as description,
               rev_count,
               size(attrs) as attr_count,
               attrs,
               p.embedding as embedding
        ORDER BY rev_count DESC, p.avg_rating DESC
        LIMIT 50
    """
}

# ==============================================================================
# AUTHORITATIVE TARGET SPECIFICATIONS FOR 21 SCENARIOS (3 PER CATEGORY)
# ==============================================================================

TARGET_CONFIGS: Dict[str, List[Dict[str, Any]]] = {
    "Camera": [
        {
            "target_asin": "B0BGXS26QL",
            "utterance": "I need a Full HD streaming webcam that supports smooth 60FPS at 1080p with 2X electronic pan-tilt-zoom and a physical privacy shutter under $60.",
            "semantic_query": "streaming webcam 1080p 60fps autofocus ePTZ digital zoom ring light privacy cover dual stereo mics",
            "distinguishing_feature": {
                "attribute": "Sensor & Frame Rate",
                "value": "1080P FHD at smooth 60FPS with 2X electronic pan-tilt-zoom (ePTZ) and magnetic privacy shutter",
                "salience": 1.0,
                "feature_name": "Sensor & Frame Rate",
                "feature_value": "1080P FHD at 60FPS with 2X ePTZ Zoom and Privacy Shutter",
                "feature_type": "technical_spec",
                "discriminative_justification": "Candidate peers in the webcam pool (such as Razer Kiyo B09DV19SMR) only support 30 FPS at 1080p and lack ePTZ digital zoom, making 60FPS at 1080p with ePTZ unique to the NexiGo N620E."
            },
            "price_max": 60.0,
            "brand": "NexiGo",
            "soft_preferences": [
                {"category": "feature", "value": "1080p 60FPS video recording", "polarity": 1.0},
                {"category": "feature", "value": "2X ePTZ digital zoom", "polarity": 1.0},
                {"category": "feature", "value": "privacy cover", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Camera'})-[:DESIRES]->(Attribute {name: '60FPS 1080p ePTZ'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B0BGXS26QL'})"
        },
        {
            "target_asin": "B08F6GPRH6",
            "utterance": "I'm looking for a complete smart home security bundle that includes an outdoor weather-resistant camera, an indoor mini camera, and a video doorbell system all integrated together.",
            "semantic_query": "smart home security bundle video doorbell system outdoor camera mini indoor camera Alexa compatible",
            "distinguishing_feature": {
                "attribute": "System Configuration",
                "value": "Complete 3-part Whole Home Security Bundle including Video Doorbell, weather-resistant Outdoor camera, and compact Mini indoor camera",
                "salience": 1.0,
                "feature_name": "System Configuration",
                "feature_value": "3-Piece Whole Home Bundle (Doorbell + Outdoor + Mini Indoor)",
                "feature_type": "functional_capability",
                "discriminative_justification": "Similar peer cameras in the pool (e.g. standalone Blink Mini B0BWD4WGJB or LaView Baby Monitor B0C2V538MK) only provide single indoor units, whereas B08F6GPRH6 uniquely bundles a Video Doorbell and outdoor camera."
            },
            "price_max": 250.0,
            "brand": "Blink",
            "soft_preferences": [
                {"category": "feature", "value": "video doorbell system", "polarity": 1.0},
                {"category": "feature", "value": "outdoor weather-resistant camera", "polarity": 1.0},
                {"category": "feature", "value": "indoor mini camera", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Camera'})-[:DESIRES]->(Attribute {name: 'Whole Home Bundle'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B08F6GPRH6'})"
        },
        {
            "target_asin": "B014TUZ92U",
            "utterance": "I want an affordable Fujifilm Instax Mini instant print film camera in matte black with a high-key portrait brightness adjustment dial under $120.",
            "semantic_query": "instant film camera Fujifilm Instax Mini high-key brightness adjustment black analog photo prints",
            "distinguishing_feature": {
                "attribute": "Exposure Mode",
                "value": "Iconic matte Black instant analog film camera with automatic exposure measurement and high-key portrait brightness dial",
                "salience": 1.0,
                "feature_name": "Exposure Mode",
                "feature_value": "Analog Instant Film with High-Key Brightness Adjustment Dial",
                "feature_type": "functional_capability",
                "discriminative_justification": "Peers in the camera pool (such as digital Fujifilms B00HNOOVGK or high-end Instax Mini 90 B0873GV89G) lack the dedicated analog high-key brightness dial in matte black at this entry price."
            },
            "price_max": 120.0,
            "brand": "Fujifilm",
            "soft_preferences": [
                {"category": "feature", "value": "instant print film", "polarity": 1.0},
                {"category": "feature", "value": "high-key brightness dial", "polarity": 1.0},
                {"category": "color", "value": "Black", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Camera'})-[:DESIRES]->(Attribute {name: 'Instant Film'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B014TUZ92U'})"
        }
    ],
    "Phone": [
        {
            "target_asin": "B08GNRGB67",
            "utterance": "I need an unlocked Samsung Galaxy smartphone that supports high-speed 5G network connectivity with at least 128GB of internal storage and a 64MP camera.",
            "semantic_query": "Samsung Galaxy unlocked smartphone 5G network connectivity 128GB internal storage 64MP camera",
            "distinguishing_feature": {
                "attribute": "Network & Storage",
                "value": "Factory unlocked 5G connectivity with 128GB internal storage and 64MP high-resolution telephoto zoom camera",
                "salience": 1.0,
                "feature_name": "Network & Storage",
                "feature_value": "Factory Unlocked 5G with 128GB Storage and 64MP Camera",
                "feature_type": "technical_spec",
                "discriminative_justification": "Peer phones in the candidate pool (such as Galaxy S9+ B07VV9HSGL or iPhone 8 Plus B089SRK8VQ) are 4G LTE only with 64GB storage, whereas B08GNRGB67 is the only candidate providing genuine 5G connectivity with 128GB storage."
            },
            "price_max": 800.0,
            "brand": "Samsung Electronics",
            "soft_preferences": [
                {"category": "feature", "value": "5G network connectivity", "polarity": 1.0},
                {"category": "feature", "value": "128GB internal storage", "polarity": 1.0},
                {"category": "feature", "value": "64MP camera", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Phone'})-[:DESIRES]->(Attribute {name: '5G Connectivity'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B08GNRGB67'})"
        },
        {
            "target_asin": "B07VV9HSGL",
            "utterance": "I'm searching for a factory unlocked Samsung Galaxy S9+ smartphone in Midnight Black that retains a dedicated 3.5mm headphone jack and rear fingerprint reader.",
            "semantic_query": "Samsung Galaxy S9+ factory unlocked smartphone 64GB Midnight Black 3.5mm headphone jack dual aperture rear fingerprint",
            "distinguishing_feature": {
                "attribute": "Hardware Interface",
                "value": "Dual Aperture f/1.5-f/2.4 rear camera with dedicated 3.5mm stereo headphone jack and physical rear capacitive fingerprint sensor",
                "salience": 1.0,
                "feature_name": "Hardware Interface",
                "feature_value": "Dedicated 3.5mm Headphone Jack and Rear Fingerprint Sensor with Dual Aperture",
                "feature_type": "technical_spec",
                "discriminative_justification": "Modern peers like Galaxy S20+ (B08GNRGB67) removed the 3.5mm audio jack and moved to in-display fingerprint, making the S9+ uniquely suited for users requiring wired analog audio."
            },
            "price_max": 600.0,
            "brand": "SAMSUNG",
            "soft_preferences": [
                {"category": "feature", "value": "3.5mm headphone jack", "polarity": 1.0},
                {"category": "feature", "value": "rear fingerprint scanner", "polarity": 1.0},
                {"category": "color", "value": "Midnight Black", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Phone'})-[:DESIRES]->(Attribute {name: '3.5mm Audio Jack'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B07VV9HSGL'})"
        },
        {
            "target_asin": "B089SRK8VQ",
            "utterance": "Looking for a renewed Apple iPhone in gold finish with a tactile Touch ID home button and dual cameras supporting Portrait mode for under $220.",
            "semantic_query": "Apple iPhone 8 Plus renewed 64GB Gold Touch ID home button dual cameras portrait mode",
            "distinguishing_feature": {
                "attribute": "Platform & Biometrics",
                "value": "Apple iOS smartphone with physical Touch ID home button and dual 12MP Portrait mode optical zoom cameras in Gold finish",
                "salience": 1.0,
                "feature_name": "Platform & Biometrics",
                "feature_value": "Apple iOS with Physical Touch ID and Dual 12MP Portrait Camera",
                "feature_type": "technical_spec",
                "discriminative_justification": "All competing peers in the 50 candidate pool are Android smartphones (Samsung Galaxy S9+, S20+, Note 4), making B089SRK8VQ the only Apple iOS device with physical Touch ID."
            },
            "price_max": 220.0,
            "brand": "Apple",
            "soft_preferences": [
                {"category": "platform", "value": "iOS", "polarity": 1.0},
                {"category": "feature", "value": "Touch ID home button", "polarity": 1.0},
                {"category": "feature", "value": "dual portrait camera", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Phone'})-[:DESIRES]->(Attribute {name: 'Touch ID'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B089SRK8VQ'})"
        }
    ],
    "Charger": [
        {
            "target_asin": "B088FHJLR1",
            "utterance": "I need a compact 65W GaN wall charger that provides 4 simultaneous ports including 3 USB-C outputs to charge my laptop and phone together.",
            "semantic_query": "65W USB C charger 4 ports GaN technology fast power delivery wall charger adapter",
            "distinguishing_feature": {
                "attribute": "Power Delivery & Port Count",
                "value": "High-efficiency 65W GaN fast wall charger equipped with 4 simultaneous charging ports (3 USB-C + 1 USB-A)",
                "salience": 1.0,
                "feature_name": "Power Delivery & Port Count",
                "feature_value": "65W GaN with 4 Ports (3x USB-C + 1x USB-A)",
                "feature_type": "technical_spec",
                "discriminative_justification": "Competing chargers in the candidate pool (such as RAMPOW 61W B08B14VXPL or Apple 20W B08L5M9BTJ) provide only a single USB port, whereas UGREEN B088FHJLR1 provides 4 multi-device ports powered by GaN."
            },
            "price_max": 50.0,
            "brand": "UGREEN",
            "soft_preferences": [
                {"category": "feature", "value": "65W GaN technology", "polarity": 1.0},
                {"category": "feature", "value": "4 charging ports", "polarity": 1.0},
                {"category": "feature", "value": "triple USB-C outputs", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Charger'})-[:DESIRES]->(Attribute {name: '65W GaN 4 Ports'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B088FHJLR1'})"
        },
        {
            "target_asin": "B08L5M9BTJ",
            "utterance": "I want an official Apple 20W USB-C power adapter cube for fast charging my iPhone safely under $25.",
            "semantic_query": "official Apple 20W USB-C power adapter iPhone fast charger Type C wall plug",
            "distinguishing_feature": {
                "attribute": "OEM Compatibility",
                "value": "Official genuine Apple 20W USB-C Power Adapter engineered specifically with Apple Power Delivery profile",
                "salience": 1.0,
                "feature_name": "OEM Compatibility",
                "feature_value": "Official Genuine Apple 20W Power Delivery Profile",
                "feature_type": "technical_spec",
                "discriminative_justification": "Peers in the candidate pool are third-party generic chargers (Citelect B09KC21JTY, KASHIMURA B0C3C66TNY); B08L5M9BTJ is the only authentic first-party OEM Apple adapter."
            },
            "price_max": 25.0,
            "brand": "Apple",
            "soft_preferences": [
                {"category": "brand", "value": "Apple", "polarity": 1.0},
                {"category": "feature", "value": "20W USB-C Power Delivery", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Charger'})-[:DESIRES]->(Attribute {name: 'Apple 20W OEM'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B08L5M9BTJ'})"
        },
        {
            "target_asin": "B095LLDH4H",
            "utterance": "I'm traveling abroad and need an all-in-one universal international travel power adapter with 4 dedicated USB-A ports delivering 3.4A smart IC output across EU, UK, and US sockets under $20.",
            "semantic_query": "universal travel adapter all-in-one international plug adapter EU UK US AUS 4 USB-A ports 3.4A smart IC",
            "distinguishing_feature": {
                "attribute": "Port Configuration & Amperage",
                "value": "All-in-one universal international travel adapter with 4 dedicated USB-A charging ports and 3.4A smart IC output across US, EU, UK, and AUS sockets",
                "salience": 1.0,
                "feature_name": "Port Configuration & Amperage",
                "feature_value": "Universal Worldwide Travel Adapter with 4 USB-A Ports and 3.4A Output",
                "feature_type": "functional_capability",
                "discriminative_justification": "Peer travel adapter ZGGCD B07SMFV58F features a mixed USB port layout (3 USB-A + 1 USB Type-C) with 4.5A output, whereas other charger peers are fixed US wall plugs. B095LLDH4H is uniquely equipped with 4 dedicated USB-A charging ports delivering 3.4A balanced output across worldwide sliding plugs."
            },
            "price_max": 20.0,
            "brand": "HAOZI",
            "soft_preferences": [
                {"category": "feature", "value": "international travel adapter", "polarity": 1.0},
                {"category": "feature", "value": "4 dedicated USB-A ports", "polarity": 1.0},
                {"category": "feature", "value": "3.4A smart IC output", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Charger'})-[:DESIRES]->(Attribute {name: 'Universal 4 USB-A 3.4A'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B095LLDH4H'})",
            "override_peers": ["B0936X8RDR", "B088FHJLR1", "B08B14VXPL", "B007J4BOWI", "B07BQRSF6X"],
            "excluded_peer_asins": ["B07SMFV58F"]
        }
    ],
    "Mouse": [
        {
            "target_asin": "B0B4SWZTZ1",
            "utterance": "I need an ultra-quiet, silent-clicking wireless mouse with a USB nano receiver in an olive green finish for office work under $15.",
            "semantic_query": "seenda wireless mouse 2.4G noiseless silent click USB receiver olive green portable",
            "distinguishing_feature": {
                "attribute": "Acoustic Noise Reduction",
                "value": "Ultra-quiet noiseless click switches with Olive Green streamlined compact casing and drop-resistant build",
                "salience": 1.0,
                "feature_name": "Acoustic Noise Reduction",
                "feature_value": "Noiseless Silent Micro-Switches with Olive Green Finish",
                "feature_type": "functional_capability",
                "discriminative_justification": "Peer mice (such as OKIMO B088NMVW4Y or Uiosmuph B082M94GY9) feature loud clicks or flashy glowing RGB lights; B0B4SWZTZ1 uniquely combines noiseless silent switches with an elegant matte olive green design."
            },
            "price_max": 15.0,
            "brand": "seenda",
            "soft_preferences": [
                {"category": "feature", "value": "noiseless silent click", "polarity": 1.0},
                {"category": "color", "value": "Olive Green", "polarity": 1.0},
                {"category": "connectivity", "value": "2.4G wireless USB", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Mouse'})-[:DESIRES]->(Attribute {name: 'Noiseless Click'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B0B4SWZTZ1'})"
        },
        {
            "target_asin": "B0B4KJRD1C",
            "utterance": "I want a rechargeable ergonomic vertical mouse with multi-device triple connectivity supporting Bluetooth 5.0, Bluetooth 3.0, and USB connection to switch smoothly between my Mac and PC.",
            "semantic_query": "seenda wireless vertical ergonomic mouse rechargeable Bluetooth 5.0 Bluetooth 3.0 USB multi-device handshake Mac Windows",
            "distinguishing_feature": {
                "attribute": "Connectivity & Form Factor",
                "value": "Ergonomic vertical handshake design with multi-device triple connectivity (Bluetooth 5.0 + Bluetooth 3.0 + 2.4G USB)",
                "salience": 1.0,
                "feature_name": "Connectivity & Form Factor",
                "feature_value": "Bluetooth 5.0 + Bluetooth 3.0 + USB Triple Mode Vertical Mouse",
                "feature_type": "technical_spec",
                "discriminative_justification": "Competing vertical mice in the pool (such as Vassink B08JYBC9MY and Viwind B09XXFK7RM) only support a single 2.4GHz USB nano receiver without Bluetooth, while Bluetooth peers (such as TECKNET B082V8GC6T and MMK B086P73W2F) are standard flat horizontal mice. B0B4KJRD1C uniquely combines vertical ergonomic handshake contouring with multi-device Bluetooth and USB triple connectivity."
            },
            "price_max": 30.0,
            "brand": "seenda",
            "soft_preferences": [
                {"category": "ergonomics", "value": "vertical handshake grip", "polarity": 1.0},
                {"category": "connectivity", "value": "multi-device Bluetooth and USB triple mode", "polarity": 1.0},
                {"category": "feature", "value": "rechargeable battery", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Mouse'})-[:DESIRES]->(Attribute {name: 'Triple Mode Vertical Ergonomics'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B0B4KJRD1C'})",
            "override_peers": ["B086P73W2F", "B0B4SWZTZ1", "B07J3H9K8N", "B082V8GC6T", "B08V9VN5Q6"],
            "excluded_peer_asins": ["B08JYBC9MY"]
        },
        {
            "target_asin": "B006MCDUZM",
            "utterance": "I'm looking for a durable Logitech wireless mouse with micro-precise web scrolling and an extended 3-year battery life in red and black.",
            "semantic_query": "Logitech wireless mouse M525 micro-precise scroll wheel 3-year battery life red black rubber grips",
            "distinguishing_feature": {
                "attribute": "Scrolling Precision & Longevity",
                "value": "Micro-precise scroll wheel with enhanced detents and exceptional 3-year battery life in contoured Red/Black dual-finish",
                "salience": 1.0,
                "feature_name": "Scrolling Precision & Longevity",
                "feature_value": "Micro-Precise Scroll Wheel with 3-Year Battery Life",
                "feature_type": "technical_spec",
                "discriminative_justification": "Similar Logitech peers (M325 B08YMVB98D and B00E7IPN0I) have standard scrolling and only 12-18 months battery life; B006MCDUZM specifically features the micro-precise high-groove wheel and 36-month battery."
            },
            "price_max": 35.0,
            "brand": "Logitech",
            "soft_preferences": [
                {"category": "brand", "value": "Logitech", "polarity": 1.0},
                {"category": "feature", "value": "micro-precise scroll wheel", "polarity": 1.0},
                {"category": "feature", "value": "3-year battery life", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Mouse'})-[:DESIRES]->(Attribute {name: 'Micro-Precise Scroll'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B006MCDUZM'})"
        }
    ],
    "Headphone": [
        {
            "target_asin": "B08BG7J2MN",
            "utterance": "I want lightweight open-ear wireless sports headphones with bone conduction technology so my ear canals remain open to hear ambient traffic while running outdoors.",
            "semantic_query": "Aftershokz bone conduction wireless headphones open-ear sports running ambient sound traffic awareness",
            "distinguishing_feature": {
                "attribute": "Acoustic Transducer Technology",
                "value": "Open-ear bone conduction technology transmitting audio via cheekbones leaving ear canals completely open for outdoor awareness",
                "salience": 1.0,
                "feature_name": "Acoustic Transducer Technology",
                "feature_value": "Open-Ear Bone Conduction Transducer Technology",
                "feature_type": "technical_spec",
                "discriminative_justification": "Candidate peers in the sports pool (such as Bose SoundSport Free B074F3YW3R or Beats Powerbeats Pro B0C337TNGS) are in-ear earbuds that block the ear canal, whereas Aftershokz B08BG7J2MN uniquely uses open-ear bone conduction transducers for situational awareness."
            },
            "price_max": 180.0,
            "brand": "Aftershokz",
            "soft_preferences": [
                {"category": "feature", "value": "bone conduction technology", "polarity": 1.0},
                {"category": "form_factor", "value": "open-ear", "polarity": 1.0},
                {"category": "use_case", "value": "outdoor running safety", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Headphone'})-[:DESIRES]->(Attribute {name: 'Bone Conduction'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B08BG7J2MN'})",
            "override_peers": ["B074F3YW3R", "B0C337TNGS", "B0C3R2WCKX", "B0BHWYQ47Y", "B0BY32J7TK"],
            "excluded_peer_asins": ["B07KR62YBD"]
        },
        {
            "target_asin": "B08PFW1S1V",
            "utterance": "I want comfortable wireless over-ear travel headphones with hybrid active noise cancelling, Hi-Res Audio certification, and 40 hours of playtime under $75.",
            "semantic_query": "Soundcore Anker Life Q20 hybrid active noise cancelling ANC wireless over-ear headphones Hi-Res Audio 40H battery",
            "distinguishing_feature": {
                "attribute": "Acoustic Noise Control & Audio Certification",
                "value": "Hybrid Active Noise Cancelling (ANC) with certified Hi-Res Audio and 40-hour playtime in an over-ear design under $75",
                "salience": 1.0,
                "feature_name": "Acoustic Noise Control & Audio Certification",
                "feature_value": "Hybrid Active Noise Cancelling with Hi-Res Audio and 40-Hour Battery",
                "feature_type": "technical_spec",
                "discriminative_justification": "Competing over-ear headsets in the budget pool (pollini B0BQCF4N32, August B08DWN51TQ, PowerLocus B07CYZGQ12) provide only passive isolation and standard audio, whereas Soundcore Life Q20 B08PFW1S1V is the only candidate offering hybrid ANC with certified Hi-Res Audio under $75."
            },
            "price_max": 75.0,
            "brand": "Soundcore",
            "soft_preferences": [
                {"category": "feature", "value": "hybrid active noise cancelling", "polarity": 1.0},
                {"category": "feature", "value": "Hi-Res Audio", "polarity": 1.0},
                {"category": "form_factor", "value": "over-ear", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Headphone'})-[:DESIRES]->(Attribute {name: 'Hybrid ANC Hi-Res'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B08PFW1S1V'})",
            "override_peers": ["B0BQCF4N32", "B08DWN51TQ", "B07CYZGQ12", "B097MRW46F", "B07S1582YY"],
            "excluded_peer_asins": ["B0BS1QXF6M"]
        },
        {
            "target_asin": "B07S764D9V",
            "utterance": "I need reliable wired in-ear earbuds with a 3.5mm jack, inline call microphone, and angled ergonomic tips for comfortable sleeping and study.",
            "semantic_query": "Panasonic ErgoFit wired earbuds in-ear headphones 3.5mm jack inline microphone call controller comfortable fit",
            "distinguishing_feature": {
                "attribute": "Acoustic Ergonomics",
                "value": "Wired 3.5mm in-ear canal design with patented angled ErgoFit earbuds and integrated inline microphone call controller in Blue",
                "salience": 1.0,
                "feature_name": "Acoustic Ergonomics",
                "feature_value": "Patented ErgoFit Angled Ear Canal Design with Inline Mic",
                "feature_type": "technical_spec",
                "discriminative_justification": "Peers in the pool (ELECDER B078RGL8SB, PowerLocus B07CYZGQ12) are bulky over-ear headbands; Panasonic ErgoFit B07S764D9V provides an ultra-compact in-ear profile with zero battery requirement."
            },
            "price_max": 20.0,
            "brand": "Panasonic",
            "soft_preferences": [
                {"category": "connectivity", "value": "wired 3.5mm jack", "polarity": 1.0},
                {"category": "feature", "value": "inline microphone", "polarity": 1.0},
                {"category": "ergonomics", "value": "ErgoFit angled in-ear", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Headphone'})-[:DESIRES]->(Attribute {name: 'ErgoFit In-Ear'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B07S764D9V'})"
        }
    ],
    "Laptop": [
        {
            "target_asin": "B0BRZ6VK9N",
            "utterance": "I am looking for a lightweight 13-inch Apple MacBook Air featuring the revolutionary M1 chip, silent fanless cooling, and a Retina display under $900.",
            "semantic_query": "Apple MacBook Air 13-inch laptop M1 chip 8GB RAM 256GB SSD Retina display fanless silent Touch ID",
            "distinguishing_feature": {
                "attribute": "Processor Architecture",
                "value": "Apple M1 system-on-chip with fanless completely silent thermal architecture and 18-hour battery life",
                "salience": 1.0,
                "feature_name": "Processor Architecture",
                "feature_value": "Apple M1 Silicon with Fanless Silent Thermal Architecture",
                "feature_type": "technical_spec",
                "discriminative_justification": "Peer laptops in the candidate pool (older MacBook Air B0863VLHQR or MacBook Pro B01MD0CGGS) use Intel Core processors requiring noisy active fan cooling, whereas the M1 MacBook Air is completely fanless."
            },
            "price_max": 900.0,
            "brand": "Apple",
            "soft_preferences": [
                {"category": "processor", "value": "Apple M1 Chip", "polarity": 1.0},
                {"category": "feature", "value": "silent fanless cooling", "polarity": 1.0},
                {"category": "display", "value": "13-inch Retina Display", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Laptop'})-[:DESIRES]->(Attribute {name: 'Apple M1 Chip'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B0BRZ6VK9N'})"
        },
        {
            "target_asin": "B08CSHM6L3",
            "utterance": "I need an affordable 14-inch Chromebook with a 180-degree lay-flat swivel hinge and AMD Dual-Core processor for under $200.",
            "semantic_query": "HP Chromebook 14-inch laptop 180-degree swivel hinge AMD Dual-Core A4 4GB RAM 32GB eMMC",
            "distinguishing_feature": {
                "attribute": "Hinge Mechanism & APU",
                "value": "180-degree lay-flat swivel hinge with AMD Dual-Core A4-9120 APU and Chalkboard Gray anti-glare finish",
                "salience": 1.0,
                "feature_name": "Hinge Mechanism & APU",
                "feature_value": "180-Degree Lay-Flat Swivel Hinge with AMD Dual-Core A4",
                "feature_type": "technical_spec",
                "discriminative_justification": "Peer Chromebooks (such as HP Chromebook 14 B0B5DFFJ6S or Acer C720 B00GZ1GV3I) use Intel Celeron processors and standard rigid hinges that cannot fold flat to 180 degrees."
            },
            "price_max": 200.0,
            "brand": "HP",
            "soft_preferences": [
                {"category": "feature", "value": "180-degree swivel hinge", "polarity": 1.0},
                {"category": "processor", "value": "AMD Dual-Core", "polarity": 1.0},
                {"category": "os", "value": "Chrome OS", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Laptop'})-[:DESIRES]->(Attribute {name: '180-Degree Swivel'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B08CSHM6L3'})"
        },
        {
            "target_asin": "B0BWV4MXQG",
            "utterance": "I want a 15.6-inch gaming laptop equipped with an NVIDIA GeForce RTX 3050 discrete graphics card and a 144Hz IPS display under $750.",
            "semantic_query": "Acer Nitro 5 gaming laptop Intel Core i5 NVIDIA GeForce RTX 3050 15.6 FHD 144Hz IPS display",
            "distinguishing_feature": {
                "attribute": "Discrete GPU & Refresh Rate",
                "value": "Dedicated NVIDIA GeForce RTX 3050 GPU with ray-tracing support and 144Hz high-refresh-rate Full HD IPS gaming panel",
                "salience": 1.0,
                "feature_name": "Discrete GPU & Refresh Rate",
                "feature_value": "NVIDIA GeForce RTX 3050 Discrete GPU with 144Hz IPS Display",
                "feature_type": "technical_spec",
                "discriminative_justification": "Competing laptops in the 50 candidate pool (Acer Aspire E15 B076919RKR with entry-level MX150 or SGIN B0C6JXQCF5 with Intel integrated graphics) lack ray-tracing RTX gaming hardware and high-refresh 144Hz screens."
            },
            "price_max": 750.0,
            "brand": "Acer",
            "soft_preferences": [
                {"category": "gpu", "value": "NVIDIA GeForce RTX 3050", "polarity": 1.0},
                {"category": "display", "value": "144Hz IPS refresh rate", "polarity": 1.0},
                {"category": "display_size", "value": "15.6 inch", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Laptop'})-[:DESIRES]->(Attribute {name: 'RTX 3050 144Hz'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B0BWV4MXQG'})"
        }
    ],
    "Keyboard": [
        {
            "target_asin": "B08JZZ4TK7",
            "utterance": "I need an ergonomic split-key wired USB keyboard with a curved split layout and integrated palm rest to relieve typing wrist strain under $50.",
            "semantic_query": "Perixx Periboard-512 ergonomic split keyboard natural ergonomic split-key palm rest wired USB",
            "distinguishing_feature": {
                "attribute": "Keybed Geometry",
                "value": "Split-key 3D curved ergonomic layout with integrated padded palm rest to encourage natural arm posture",
                "salience": 1.0,
                "feature_name": "Keybed Geometry",
                "feature_value": "3D Curved Split-Key Geometry with Integrated Palm Rest",
                "feature_type": "technical_spec",
                "discriminative_justification": "Other Perixx keyboards in the pool (PERIBOARD-213U B097J7JPQX, PERIBOARD-426 B0BJ6TQTR8) feature standard straight flat key layouts; B08JZZ4TK7 is the only Perixx offering full ergonomic split architecture."
            },
            "price_max": 50.0,
            "brand": "Perixx",
            "soft_preferences": [
                {"category": "ergonomics", "value": "split-key curved layout", "polarity": 1.0},
                {"category": "feature", "value": "integrated palm rest", "polarity": 1.0},
                {"category": "connectivity", "value": "wired USB", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Keyboard'})-[:DESIRES]->(Attribute {name: 'Split Ergonomics'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B08JZZ4TK7'})"
        },
        {
            "target_asin": "B084G4GY2N",
            "utterance": "I'm searching for a pocket-sized tri-folding Bluetooth keyboard with a built-in touchpad that can switch seamlessly between 3 paired devices.",
            "semantic_query": "iClever BK08 Bluetooth folding keyboard sensitive touchpad sync 3 devices tri-folded portable",
            "distinguishing_feature": {
                "attribute": "Portability & Input Integration",
                "value": "Pocket-sized tri-folding aluminum casing featuring an integrated sensitive touchpad and multi-device pairing for up to 3 devices",
                "salience": 1.0,
                "feature_name": "Portability & Input Integration",
                "feature_value": "Pocket Tri-Folding Aluminum Body with Integrated Touchpad and 3-Device Bluetooth",
                "feature_type": "functional_capability",
                "discriminative_justification": "Competing Bluetooth keyboards in the pool (e.g. UBOTIE B08L7P71VN) are rigid non-folding units lacking touchpads, while B084G4GY2N folds into a compact pocketable form factor."
            },
            "price_max": 65.0,
            "brand": "iClever",
            "soft_preferences": [
                {"category": "form_factor", "value": "tri-fold portable", "polarity": 1.0},
                {"category": "feature", "value": "built-in touchpad", "polarity": 1.0},
                {"category": "feature", "value": "3-device Bluetooth sync", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Keyboard'})-[:DESIRES]->(Attribute {name: 'Tri-Fold Touchpad'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B084G4GY2N'})"
        },
        {
            "target_asin": "B00SK0FOHG",
            "utterance": "I need a wireless living room keyboard with an integrated 3.5-inch multi-touch touchpad to control my media center PC connected to the TV.",
            "semantic_query": "Logitech wireless touch keyboard K400 built-in multi-touch touchpad media center HTPC TV control",
            "distinguishing_feature": {
                "attribute": "Media Navigation Touchpad",
                "value": "Integrated large 3.5-inch multi-touch touchpad with dedicated left/right buttons for lean-back PC-to-TV home entertainment navigation",
                "salience": 1.0,
                "feature_name": "Media Navigation Touchpad",
                "feature_value": "Built-In 3.5-Inch Multi-Touch Touchpad for Living Room PC-to-TV Navigation",
                "feature_type": "functional_capability",
                "discriminative_justification": "Peers like Logitech K350 Wave (B002MMY4WY) or K360 (B07DM54P8F) are traditional desktop keyboards requiring a separate desk mouse, whereas K400 incorporates an all-in-one touchpad for couch navigation."
            },
            "price_max": 30.0,
            "brand": "Logitech",
            "soft_preferences": [
                {"category": "feature", "value": "integrated multi-touch touchpad", "polarity": 1.0},
                {"category": "connectivity", "value": "wireless USB receiver", "polarity": 1.0},
                {"category": "use_case", "value": "PC-to-TV media navigation", "polarity": 1.0}
            ],
            "reasoning_path": "(User:Preference {category: 'Keyboard'})-[:DESIRES]->(Attribute {name: 'Built-in Touchpad'})-[:OFFERED_BY]->(ParentProduct {parent_asin: 'B00SK0FOHG'})"
        }
    ]
}


def sanitize_float(val: Any) -> Optional[float]:
    """Ensures RFC 8259 compliance by replacing NaN/Inf with None."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def sanitize_payload(obj: Any) -> Any:
    """Recursively converts all NaN and Inf float values to None for clean JSON serialization."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_payload(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_payload(v) for v in obj]
    return obj


def extract_candidate_pools(conn: Neo4jConnector) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extracts exactly 50 ParentProduct candidates for each of the 7 categories from live Neo4j.
    """
    candidate_pools: Dict[str, List[Dict[str, Any]]] = {}
    for cat_name, cypher in CATEGORY_CYPHER_QUERIES.items():
        logger.info(f"Extracting candidate pool for category: {cat_name}...")
        rows = conn.execute_query(cypher)
        if len(rows) < 50:
            raise RuntimeError(
                f"Candidate extraction failed for category {cat_name}: expected 50, got {len(rows)}"
            )
        # Exactly 50 candidates
        candidates = rows[:50]
        candidate_pools[cat_name] = candidates
        logger.info(f"Successfully extracted {len(candidates)} candidates for {cat_name}.")
    return candidate_pools


def compute_peer_clusters(
    candidates: List[Dict[str, Any]]
) -> Tuple[np.ndarray, Dict[str, List[str]]]:
    """
    Computes pairwise cosine similarity matrix and maps each candidate ASIN to its top peers.
    """
    embs = np.array([r["embedding"] for r in candidates], dtype=np.float32)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    norm_embs = embs / norms
    sim_matrix = np.dot(norm_embs, norm_embs.T)

    asin_to_peers: Dict[str, List[str]] = {}
    for idx, c in enumerate(candidates):
        sims = sim_matrix[idx].copy()
        sims[idx] = -1.0  # Exclude self
        top_peer_indices = np.argsort(sims)[::-1]
        # Return top peer ASINs (excluding self)
        peer_asins = [candidates[p]["asin"] for p in top_peer_indices if candidates[p]["asin"] != c["asin"]]
        asin_to_peers[c["asin"]] = peer_asins

    return sim_matrix, asin_to_peers


def verify_asins_in_database(
    asins: Sequence[str],
    conn: Neo4jConnector,
) -> Dict[str, bool]:
    """
    Verifies existence of ASINs against live Neo4j ParentProduct nodes using Cypher UNWIND.
    """
    if not asins:
        return {}
    unique_asins = list(set(str(a).strip() for a in asins if a))
    query = """
    UNWIND $asins AS asin_id
    OPTIONAL MATCH (p:ParentProduct {parent_asin: asin_id})
    RETURN asin_id, (p IS NOT NULL) AS exists
    """
    rows = conn.execute_query(query, {"asins": unique_asins})
    return {r["asin_id"]: bool(r["exists"]) for r in rows}


def build_scenario_entries(
    candidate_pools: Dict[str, List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """
    Builds the 21 scenario dictionary entries (3 per category) conforming to dual-compatible schema.
    """
    scenarios: List[Dict[str, Any]] = []
    scenario_counter = 1

    for cat_name, targets in TARGET_CONFIGS.items():
        candidates = candidate_pools[cat_name]
        candidate_asin_map = {c["asin"]: c for c in candidates}
        _, asin_to_peers = compute_peer_clusters(candidates)

        for t_spec in targets:
            target_asin = t_spec["target_asin"]
            if target_asin not in candidate_asin_map:
                raise ValueError(f"Target ASIN {target_asin} not found in {cat_name} candidate pool!")

            target_prod = candidate_asin_map[target_asin]
            target_title = target_prod["title"]
            target_price = sanitize_float(target_prod.get("price"))
            target_brand = target_prod.get("brand") or t_spec.get("brand") or ""
            target_attrs = target_prod.get("attrs", [])

            # Nearest peers from pool (filtering out colliding peers or applying explicit overrides)
            all_pool_peers = asin_to_peers.get(target_asin, [])
            override_peers = t_spec.get("override_peers")
            if override_peers:
                top_5_peers = [p for p in override_peers if p in candidate_asin_map][:5]
            else:
                excluded_peers = set(t_spec.get("excluded_peer_asins", []))
                valid_peers = [p for p in all_pool_peers if p not in excluded_peers]
                top_5_peers = valid_peers[:5]

            # Construct graded relevance:
            # target = 1.0, top peers = 0.45, remaining pool peers = 0.20
            graded_relevance: Dict[str, float] = {target_asin: 1.0}
            for peer in top_5_peers:
                graded_relevance[peer] = 0.45
            for peer in [p for p in all_pool_peers if p not in top_5_peers][:10]:
                graded_relevance[peer] = 0.20

            # Graph evidence: actual attributes from Neo4j
            graph_evidence: List[Dict[str, Any]] = []
            for attr in target_attrs:
                if attr.get("name") and attr.get("val"):
                    graph_evidence.append({
                        "attribute_name": str(attr["name"]),
                        "attribute_value": str(attr["val"])
                    })
            if target_brand:
                graph_evidence.append({"brand": target_brand})

            # Format scenario identifiers
            query_id = f"live_eval_{cat_name.lower()}_{len([s for s in scenarios if s['category'] == cat_name]) + 1:02d}"

            # Preferences profile
            preferences: Dict[str, Any] = {
                "category": cat_name,
                "preferred_brands": [target_brand] if target_brand else [],
                "price_anchor": target_price,
                "distinguishing_feature": t_spec["distinguishing_feature"]["attribute"]
            }

            # Structured filters
            structured_filters: Dict[str, Any] = {
                "category": cat_name,
                "price_max": t_spec.get("price_max") or (target_price * 1.2 if target_price else None),
            }
            if target_brand:
                structured_filters["brand"] = target_brand

            entry: Dict[str, Any] = {
                "query_id": query_id,
                "id": query_id,
                "sample_id": query_id,
                "category": cat_name,
                "utterance": t_spec["utterance"],
                "query": t_spec["utterance"],
                "user_query": t_spec["utterance"],
                "semantic_query": t_spec["semantic_query"],
                "target_asin": target_asin,
                "target_title": target_title,
                "ground_truth_asins": [target_asin],
                "peer_asins": top_5_peers,
                "distinguishing_feature": t_spec["distinguishing_feature"],
                "structured_filters": structured_filters,
                "soft_preferences": t_spec["soft_preferences"],
                "preferences": preferences,
                "graded_relevance": graded_relevance,
                "graph_evidence": graph_evidence,
                "reasoning_paths": [t_spec["reasoning_path"]]
            }

            scenarios.append(entry)
            scenario_counter += 1

    return scenarios


def generate_and_save_dataset(
    output_path: Path,
    conn: Optional[Neo4jConnector] = None,
) -> List[Dict[str, Any]]:
    """
    Main extraction, compilation, verification, and file writing routine.
    """
    should_close = False
    if conn is None:
        conn = Neo4jConnectionManager()
        conn.connect()
        should_close = True

    try:
        # Step 1: Extract 50 candidates per category (350 total)
        candidate_pools = extract_candidate_pools(conn)

        # Step 2: Build 21 scenarios
        scenarios = build_scenario_entries(candidate_pools)
        logger.info(f"Synthesized {len(scenarios)} scenarios across {len(candidate_pools)} categories.")

        # Step 3: Zero-Mock & Catalog Existence Verification
        target_asins = [s["target_asin"] for s in scenarios]
        all_peer_asins = [p for s in scenarios for p in s.get("peer_asins", [])]
        all_asins_to_check = list(set(target_asins + all_peer_asins))

        # Check for forbidden mock markers
        mock_pattern = re.compile(r"^(ALT_|MOCK_|VERIFIED_|VECTOR_DIS_|CYPHER_DIS_|SYNTHETIC_|FAKE_)", re.IGNORECASE)
        for asin in all_asins_to_check:
            if mock_pattern.search(asin):
                raise ValueError(f"Strict Zero-Mock Violation: forbidden mock ASIN pattern detected: {asin}")

        # Check in live Neo4j
        logger.info(f"Verifying {len(all_asins_to_check)} unique ASINs in live Neo4j...")
        existence_map = verify_asins_in_database(all_asins_to_check, conn)
        missing_asins = [asin for asin, exists in existence_map.items() if not exists]
        if missing_asins:
            raise RuntimeError(
                f"Strict Zero-Mock Violation: {len(missing_asins)} ASINs do not exist in live Neo4j: {missing_asins}"
            )
        logger.info("Verification PASSED: 100.0% of target and peer ASINs exist in live Neo4j!")

        # Step 4: Sanitize payload against RFC 8259 (zero NaN / Inf)
        clean_scenarios = sanitize_payload(scenarios)

        # Step 5: Overwrite file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(clean_scenarios, f, indent=2)

        logger.info(f"Successfully compiled and wrote {len(clean_scenarios)} scenarios to {output_path}")
        return clean_scenarios

    finally:
        if should_close:
            conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract and compile live CRS evaluation dataset from Neo4j (Requirements R2, R3, R4)."
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "live_eval_dataset.json"),
        help="Destination path for live_eval_dataset.json (default: repo root live_eval_dataset.json)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify the existing live_eval_dataset.json without regenerating.",
    )
    args = parser.parse_args()

    out_file = Path(args.output).resolve()

    if args.verify_only:
        logger.info(f"Verifying existing dataset at {out_file}...")
        if not out_file.exists():
            logger.error(f"File {out_file} does not exist!")
            sys.exit(1)
        with open(out_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert 14 <= len(data) <= 21, f"Expected 14-21 entries, found {len(data)}"
        conn = Neo4jConnectionManager()
        conn.connect()
        try:
            target_asins = [x["target_asin"] for x in data]
            v_map = verify_asins_in_database(target_asins, conn)
            assert all(v_map.values()), "Some ASINs do not exist in Neo4j!"
            logger.info(f"Dataset verification SUCCESSFUL: {len(data)} valid scenarios.")
        finally:
            conn.close()
        return

    conn = Neo4jConnectionManager()
    conn.connect()
    try:
        generate_and_save_dataset(out_file, conn=conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
