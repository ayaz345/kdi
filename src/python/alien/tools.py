#!/usr/bin/env python
#
# Copyright (C) 2006 Josh Taylor (Kosmix Corporation)
# Created 2006-03-29
# 
# This file is part of Alien.
# 
# Alien is free software; you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or any later version.
# 
# Alien is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
# 
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

from alien.vstruct import StructBase
from alien.array import ArrayBase


def sizeof(x,ver=None):
    try:
        fsize = x._sizeof(ver)
        return fsize(x) if callable(fsize) else fsize
    except AttributeError:
        pass
    try:
        return len(x)
    except TypeError:
        raise TypeError('sizeof Python native object is meaningless')

#----------------------------------------------------------------------------
# Browse records
#----------------------------------------------------------------------------
def browseRecords(filenames, rver):
    for fn in filenames:
        if fn == '-':
            import sys
            f = sys.stdin
        else:
            f = file(fn)
        for r in iter_records(f, rver):
            print r.typecode, r.version, r.length,
            d = r.data
            print repr(d)
            print ' ', format_struct(d, 2)
        f.close()

def record_main():
    import optparse
    op = optparse.OptionParser()
    op.add_option('-V', '--version', type='int', default=Record.__version__,
                  help='Record header version (=%default)')

    opt,args = op.parse_args()
    browseRecords(args, opt.version)

OPEN_STRUCT = 1
CLOSE_STRUCT = 2
OPEN_LIST = 3
CLOSE_LIST = 4
KV_SEP = 5
ELEM_SEP = 6

_tokStr = {
    OPEN_STRUCT : '{',
    CLOSE_STRUCT : '}',
    OPEN_LIST : '[',
    CLOSE_LIST : ']',
    KV_SEP : '=',
    ELEM_SEP : ',',
    }

def token_str(tok):
    return _tokStr.get(tok, str(tok))

def iter_struct_tokens(x):
    """iter_struct_tokens(x) --> token generator

    Recursively iterate over an Alien object and generate a list of
    value tokens.  The tokens can include a number of control tokens,
    such as:
        OPEN_STRUCT   -- begin key/value pairs
        CLOSE_STRUCT  -- end key/value pairs
        OPEN_LIST     -- begin sequence
        CLOSE_LIST    -- end sequence
        KV_SEP        -- separate key from value
        ELEM_SEP      -- separate list elements or key/value pairs

    Other items in the token stream will be string values.
    """
    if (
        getattr(x, '__nobrowse__', False)
        or not hasattr(x, '_iterattrs')
        and not isinstance(x, ArrayBase)
    ):
        yield str(x)
    elif hasattr(x, '_iterattrs'):
        yield OPEN_STRUCT
        for attr in x._iterattrs():
            yield attr
            yield KV_SEP
            value = getattr(x, attr)
            yield from iter_struct_tokens(value)
            yield ELEM_SEP
        yield CLOSE_STRUCT
    else:
        yield OPEN_LIST
        for elem in x:
            yield from iter_struct_tokens(elem)
            yield ELEM_SEP
        yield CLOSE_LIST

def closing_token_nearby(push_it, open_tok, close_tok, nChars, allowNesting):
    """closing_token_nearby(push_it, open_tok, close_tok, nChars, allowNesting) --> boolean

    Scan through a sequence of tokens to see if a closing token that
    matches an opening token appears within a certain number of
    characters.  This is used by the formatting function to decide
    when to do line wrapping.
    """
    buf = []
    depth = 1
    for tok in push_it:
        buf.append(tok)
        tokLen = 1 if tok == ELEM_SEP else 1 + len(token_str(tok))
        if not allowNesting and tok in (OPEN_STRUCT, OPEN_LIST):
            nChars = -1
            break
        elif tok == open_tok:
            depth += 1
        elif tok == close_tok:
            depth -= 1
        nChars -= tokLen
        if nChars <= 0 or depth == 0:
            break
    while buf:
        push_it.push(buf.pop())
    return nChars > 0

def elide_trailing_separators(it):
    """elide_trailing_separators(it) --> filtered iterator

    Filter trailing ELEM_SEP tokens out of a sequence.  A trailing
    ELEM_SEP is one that is immediately followed by CLOSE_STRUCT or
    CLOSE_LIST.
    """
    for last in it:
        break
    else:
        return
    for next in it:
        if last != ELEM_SEP or next not in (CLOSE_STRUCT, CLOSE_LIST):
            yield last
        last = next
    yield last


LAYOUT_COMPACT = 0
LAYOUT_NORMAL = 1
LAYOUT_EXTENDED = 2
LAYOUT_SUPER_EXTENDED = 3

def iter_format_struct(x, layout=LAYOUT_NORMAL, maxLen=None):
    """iter_format_struct(x, layout=LAYOUT_COMPACT, maxLen=None) --> line generator

    Recursively iterate over an Alien object and generate a sequence
    of lines suitable for pretty-printing.  This is implemented as a
    generator because the Alien objects can potentially be quite
    large.  Building a the full formatted representation all at once
    can be impractical.

    The layout parameter controls how much information is put on each
    line.  It may be one of:

        LAYOUT_COMPACT           Collapse multiple values onto same
                                 line, allow structure and list nesting

        LAYOUT_NORMAL            Collapse multiple values onto same line,
                                 disallow nesting

        LAYOUT_EXTENDED          Expand all lists and structures into
                                 multiple lines

        LAYOUT_SUPER_EXTENDED    Put each list and structure item on its
                                 own line

    The maxLen parameter controls the length of the output lines.  It
    is not a hard limit, only a guideline for the text-wrapping code.
    """
    if maxLen is None:
        import util.term
        maxLen = util.term.dimensions()[0] - 3
    maxLen = int(maxLen)

    if layout not in (LAYOUT_COMPACT, LAYOUT_NORMAL,
                      LAYOUT_EXTENDED, LAYOUT_SUPER_EXTENDED):
        raise ValueError('invalid layout: %r' % layout)

    braceStack = []

    import cStringIO
    lineBuf = cStringIO.StringIO()

    curLen = 0;
    needSpaces = 0
    extended = False # currently in an extended representation block
    emitAsap = False # emit as soon as convenient

    import util.iter
    it = iter_struct_tokens(x)
    it = elide_trailing_separators(it)
    it = util.iter.pushback_iter(it)

    for tok in it:
        # Always append if there's nothing in the line
        forceAppend = (lineBuf.tell() == 0)
        checkClose = None
        emitNow = False

        # Handle special token types
        if tok == ELEM_SEP:
            # Don't need spaces before commas, but always append
            needSpaces -= 1
            forceAppend = True
            if layout == LAYOUT_SUPER_EXTENDED:
                emitAsap = True

        elif tok == OPEN_STRUCT:
            checkClose = CLOSE_STRUCT
        elif tok == OPEN_LIST:
            checkClose = CLOSE_LIST
        elif tok in (CLOSE_STRUCT, CLOSE_LIST):
            parentExtended,parentEmitAsap = braceStack.pop()
            emitAsap = parentEmitAsap or parentExtended
            emitNow = extended
            extended = parentExtended
            
        elif tok == KV_SEP:
            if extended:
                emitAsap = True

        # Convert token into printable string
        stok = token_str(tok)

        
        if forceAppend:
            emitNow = False
        elif lineBuf.tell() + needSpaces + len(stok) > maxLen:
            emitNow = True

        # Emit current line if the new token would make it too long
        if emitNow:
            yield lineBuf.getvalue()
            lineBuf.seek(0)
            lineBuf.truncate()
            needSpaces = 2 * len(braceStack)

        # Add the current token to the line buffer
        lineBuf.write(' ' * needSpaces)
        lineBuf.write(stok)
        needSpaces = 1

        emitNow = False

        # Emit line if we've just opened a brace and won't be able to
        # fit the closing brace on the same line
        if checkClose:
            braceStack.append((extended,emitAsap))
            emitAsap = False
            if layout in (LAYOUT_EXTENDED, LAYOUT_SUPER_EXTENDED):
                extended = True
            else:
                nChars = maxLen - lineBuf.tell() - needSpaces
                allowNesting = (layout == LAYOUT_COMPACT)
                extended = not closing_token_nearby(it, tok, checkClose,
                                                    nChars, allowNesting)
            if extended:
                emitNow = True

        if emitAsap:
            if tok == ELEM_SEP:
                emitNow = True
            if tok in (CLOSE_STRUCT, CLOSE_LIST) and not parentExtended:
                emitNow = it.peek(None) != ELEM_SEP

        if emitNow:
            yield lineBuf.getvalue()
            lineBuf.seek(0)
            lineBuf.truncate()
            needSpaces = 2 * len(braceStack)
            emitAsap = False

    # Emit whatever is left in the line buffer
    yield lineBuf.getvalue()

def format_struct(x, indent=0, brace=False):
    if (
        hasattr(x, '__nobrowse__')
        or not isinstance(x, StructBase)
        and not isinstance(x, ArrayBase)
    ):
        return str(x)
    elif isinstance(x, StructBase):
        z = [
            f'{a} = {format_struct(getattr(x, a), indent + 2, True)}'
            for a in x._iterattrs()
        ]
        if brace:
            z = ['{'] + z + ['}'] if z else ['{}']
        return ('\n' + ' '*indent).join(z)
    else:
        z = [f'{format_struct(e, indent + 2, True)},' for e in x]
        if brace:
            z = ['['] + z + [']'] if z else ['[]']
        return '(len: %d) ' % len(x) + ('\n' + ' '*indent).join(z)

def iter_data(s, dtype, dver=None, start=0, nelem=None):
    sz_ = dtype._sizeof(dver)
    sz = (lambda x: sz_) if not callable(sz_) else sz_
    if nelem is not None:
        for _ in range(nelem):
            x = dtype(s, start, dver)
            start += sz(x)
            yield x
    else:
        end = s.__len__() if hasattr(s, '__len__') else len(s)
        while start < end:
            x = dtype(s, start, dver)
            start += sz(x)
            yield x

#_typetable = {
#    'outlinkgraph'      : (OutlinkGraphNode, 0),
#    'fixedoutlinkgraph' : (OutlinkGraphNode, 1),
#    'tar'               : (TarHeader, 0),
#    'pdhash'            : (PageData_Hash, 0),
#    'pddata'            : (PageData_Data, 0),
#    'pdurl'             : (PageData_Url, 0),
#    'hashidx'           : (CosmixHashIndex, 0),
#}
