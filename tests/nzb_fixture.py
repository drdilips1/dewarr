from xml.sax.saxutils import escape


def nzb_bytes(
    *,
    name="Example Book",
    filename="Example Book.m4b",
    size=4096,
    subject=None,
):
    label = subject or f'"{filename}" yEnc (1/1)'
    quoted = escape(label, {'"': "&quot;"})
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
<head><meta type="name">{escape(name)}</meta></head>
<file poster="hidden@example.test" date="1700000000" subject="{quoted}">
<groups><group>alt.binaries.books</group></groups>
<segments><segment bytes="{size}" number="1">part@example.test</segment></segments>
</file>
</nzb>
""".encode()
