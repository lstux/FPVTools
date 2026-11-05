from fleetmanager.msp import Parser, crc8_dvb_s2, encode_v1, encode_v2


def feed_all(parser, data):
    frames = [parser.feed(b) for b in data]
    return [f for f in frames if f]


def test_encode_v1_known_frame():
    # MSP_API_VERSION request: no payload, checksum = 0 ^ 1
    assert encode_v1(1) == b"$M<\x00\x01\x01"


def test_v1_roundtrip_response():
    raw = b"$M>\x03\x03\x04\x05\x01" + bytes([0x03 ^ 0x03 ^ 4 ^ 5 ^ 1])
    frames = feed_all(Parser(), raw)
    assert [(f.direction, f.code, f.payload, f.version) for f in frames] == [(">", 3, b"\x04\x05\x01", 1)]


def test_v1_bad_checksum_is_dropped():
    p = Parser()
    raw = bytearray(encode_v1(2, b"BTFL"))
    raw[-1] ^= 0xFF
    assert feed_all(p, bytes(raw)) == []
    assert p.crc_errors == 1


def test_v2_roundtrip_and_crc():
    frames = feed_all(Parser(), encode_v2(0x1234, b"hello"))
    assert [(f.code, f.payload, f.version) for f in frames] == [(0x1234, b"hello", 2)]
    bad = bytearray(encode_v2(7, b"abc"))
    bad[-1] ^= 1
    p = Parser()
    assert feed_all(p, bytes(bad)) == []
    assert p.crc_errors == 1


def test_crc8_matches_bytewise_definition():
    assert crc8_dvb_s2(b"") == 0
    # crc of a message followed by its own crc is zero
    msg = b"\x00\x10\x00\x02\x00\xaa\xbb"
    assert crc8_dvb_s2(msg + bytes([crc8_dvb_s2(msg)])) == 0


def test_parser_resyncs_after_noise():
    data = b"garbage$$M?$" + encode_v1(1, b"\x00\x01\x2e")
    frames = feed_all(Parser(), data)
    assert len(frames) == 1 and frames[0].code == 1
