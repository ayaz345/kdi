#!/usr/bin/env python
#
# Copyright (C) 2006 Josh Taylor (Kosmix Corporation)
# Created 2006-03-29
# 
# This file is part of the util library.
# 
# The util library is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or any later
# version.
# 
# The util library is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
# 
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

def first_n(it, n):
    it = iter(it)
    for _ in range(n):
        yield it.next()

def merge(inputs, key=lambda x:x):
    import heapq
    q = []
    for i,x in enumerate(inputs):
        it = iter(x)
        for v in it:
            k = key(v)
            q.append((k,i,v,it))
            break
    heapq.heapify(q)
    while q:
        k,i,v,it = q[0]
        yield v
        for v in it:
            k = key(v)
            heapq.heapreplace(q, (k,i,v,it))
            break
        else:
            heapq.heappop(q)

def binaryTransform(seq, pred, xform):
    it = iter(seq)
    for x in it:
        break
    else:
        return
    for y in it:
        if pred(x,y):
            x = xform(x,y)
        else:
            yield x
            x = y
    yield x

def uniq(seq, key=lambda x:x):
    return binaryTransform(seq, lambda x,y:key(x)==key(y), lambda x,y:x)

def uniqLast(seq, key=lambda x:x):
    return binaryTransform(seq, lambda x,y:key(x)==key(y), lambda x,y:y)

class pushback_iter(object):
    def __init__(self, iterable):
        self._it = iter(iterable)
        self._stack = []

    def __iter__(self):
        return self

    def next(self):
        return self._stack.pop() if self._stack else self._it.next()

    def push(self, v):
        self._stack.append(v)

    def peek(self, *dflt):
        if not self._stack:
            try:
                self._stack.append(self._it.next())
            except StopIteration:
                if dflt: return dflt[0]
                raise
        return self._stack[-1]

class peek_iter(object):
    def __init__(self, iterable):
        self._it = iter(iterable)
        self._peeked = False
        self._peekValue = None

    def __iter__(self):
        return self

    def next(self):
        if not self._peeked:
            return self._it.next()
        x, self._peekValue, self._peeked = self._peekValue, None, False
        return x

    def peek(self):
        if not self._peeked:
            self._peekValue = self._it.next()
            self._peeked = True
        return self._peekValue

def iter_splitter(iterable, n, x0=0, splitPred=lambda x,n: x >= n,
                  updateX=lambda x,i: x+1):
    """iter_splitter(iterable, n [, x0, splitPred, updateX]) --> generator of iterators

    Splits input sequence into multiple iterators, each yielding at
    most N elements. For example, the following code:
        for it in iter_splitter(range(10), 4):
            for x in it:
                print x,
            print
    emits:
        0 1 2 3
        4 5 6 7
        8 9
    All iterators returned by the generator will iterate over
    elements in the original sequence, in order, without holes.  For
    example:
        it_gen = iter_splitter(range(7), 3)
        it1, it2, it3 = it_gen.next(), it_gen.next(), it_gen.next()
        print it3.next(), it2.next()
        print list(it1), list(it2), list(it3)
    emits:
        0 1
        [2, 3, 4] [5, 6] []
    Note that the iterator generator will continue to yield iterators
    until the original sequence is exhausted.
    """
    it = iter(iterable)
    done = [ False ]
    def gen(ref,x0):
        try:
            x = x0
            while True:
                i = it.next()
                x = updateX(x,i)
                yield i
                if splitPred(x,n):
                    break
        except StopIteration:
            ref[0] = True
    while not done[0]:
        yield gen(done,x0)

def iter_equal_key(pushback_iterable, key, kfunc=lambda x:x):
    for x in pushback_iterable:
        if kfunc(x) == key:
            yield x
        else:
            pushback_iterable.push(x)
            break

def join(inputs, keyfuncs=None):
    """join(inputs, keyfuncs) --> iterator over tuples of iterators

    General join operator over k inputs yields a k-tuple of iterators,
    such that at least one iterator is over a non-empty sequence.  All
    elements in all iterators have the same join key.

    The join key is derived from each input value using the keyfunc
    parameter.  If not provided, the keyfunc defaults to the identity
    function for each input.  If the keyfunc is indexable, each index
    is associated with the corresponding input; otherwise the same
    keyfunc will be used for all inputs.  Individual keyfuncs that
    aren't callable will default to the identity function.
    
    Example with invariant assertions:

      inputs = (seq1, seq2, ..., seqN)
      keyfuncs = (keyfunc1, keyfunc2, ..., keyfuncN)
      for it_nTuple in join(inputs, keyfuncs):
          assert len(it_nTuple) == N
          itemCount = 0
          commonKey = None
          for it in it_nTuple:
              for i,x in enumerate(it):
                  itemCount += 1
                  if itemCount == 1:
                      commonKey = keyfuncs[i](x)
                  else:
                      assert keyfuncs[i](x) == commonKey
          assert itemCount >= 1

    Special-case join operators:

      0/1 join:

         def singleItemOrNone(it):
             for x in it:
                 break
             else:
                 return None
             for y in it:
                 raise ValueError('Got more than one element')
             else:
                 return x

         for it_nTuple in join((seq1, seq2, ..., seqN)):
             yield map(singleItemOrNone, it_nTuple)
    """

    n = len(inputs)
    iters = map(pushback_iter, inputs)

    if keyfuncs is None:
        keyfuncs = [ None ] * n
    elif not hasattr(keyfuncs, '__getitem__'):
        keyfuncs = [ keyfuncs ] * n
    for i,k in enumerate(keyfuncs):
        if not callable(k):
            keyfuncs[i] = lambda x:x

    import heapq
    q = []
    for i,it in enumerate(iters):
        for v in it:
            k = keyfuncs[i](v)
            it.push(v)
            q.append((k,i,it))
            break
    heapq.heapify(q)
    while q:
        k,i,it = q[0]
        yield tuple(iter_equal_key(it2, k, keyfuncs[j]) for j,it2 in enumerate(iters))
        while q and q[0][0] == k:
            k,i,it = q[0]
            for v in it:
                nk = keyfuncs[i](v)
                it.push(v)
                heapq.heapreplace(q, (nk,i,it))
                break
            else:
                heapq.heappop(q)
