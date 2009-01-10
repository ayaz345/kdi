//---------------------------------------------------------- -*- Mode: C++ -*-
// Copyright (C) 2006 Josh Taylor (Kosmix Corporation)
// Created 2006-01-11
// 
// This file is part of the oort library.
// 
// The oort library is free software; you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by the
// Free Software Foundation; either version 2 of the License, or any later
// version.
// 
// The oort library is distributed in the hope that it will be useful, but
// WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
// Public License for more details.
// 
// You should have received a copy of the GNU General Public License along
// with this program; if not, write to the Free Software Foundation, Inc.,
// 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
//----------------------------------------------------------------------------

#include <oort/fileio.h>
#include <oort/recordbuffer.h>
#include <oort/headers.h>
#include <warp/file.h>
#include <ex/exception.h>
#include <assert.h>
#include <boost/format.hpp>

using namespace oort;
using namespace warp;
using namespace ex;

//----------------------------------------------------------------------------
// allocHeaderBuf
//----------------------------------------------------------------------------
namespace
{
    inline void allocHeaderBuf(char * & buf, HeaderSpec const * spec)
    {
        delete[] buf;
        if(spec)
            buf = new char[spec->headerSize()];
        else
            buf = 0;
    }
}


//----------------------------------------------------------------------------
// FileInput
//----------------------------------------------------------------------------
FileInput::FileInput(file_t const & file) :
    file(file), spec(VEGA_SPEC),
    alloc(new RecordBufferAllocator(1<<20)),
    hdrBuf(0)
{
    allocHeaderBuf(hdrBuf, spec);
}

FileInput::FileInput(file_t const & file, HeaderSpec const * spec,
                     alloc_t const & alloc) :
    file(file), spec(spec), alloc(alloc), hdrBuf(0)
{
    allocHeaderBuf(hdrBuf, spec);
}

FileInput::~FileInput()
{
    delete[] hdrBuf;
}

FileInput::FileInput(FileInput const & o) :
    file(o.file), spec(o.spec), alloc(o.alloc), hdrBuf(0)
{
    allocHeaderBuf(hdrBuf, spec);
}

FileInput const & FileInput::operator=(FileInput const & o)
{
    file = o.file;
    spec = o.spec;
    alloc = o.alloc;
    allocHeaderBuf(hdrBuf, spec);
    return *this;
}

void FileInput::setFile(file_t const & f)
{
    file = f;
}

void FileInput::setHeaderSpec(HeaderSpec const * s)
{
    spec = s;
    allocHeaderBuf(hdrBuf, spec);
}

void FileInput::setAllocator(alloc_t const & a)
{
    alloc = a;
}

void FileInput::seek(off_t pos)
{
    assert(file);
    file->seek(pos);
}

bool FileInput::get(Record & r)
{
    assert(file);
    assert(spec);
    assert(alloc);
    assert(hdrBuf);

    off_t pos = file->tell();
    try {
        if(!file->read(hdrBuf, spec->headerSize(), 1))
            return false;
    
        HeaderSpec::Fields f;
        spec->deserialize(hdrBuf, f);

        size_t diskLength = f.length;
        char *diskData = 0;

        bool isCompressed = f.flags & HeaderSpec::LZO_COMPRESSED;
        lzo_uint uncompressedSize = f.length;
        if(isCompressed) {
            if(!file->read(&uncompressedSize, sizeof(lzo_uint))) {
                return false;
            }
            f.length = uncompressedSize;
            lzoBuffer.reserve(uncompressedSize);
            diskData = &lzoBuffer[0];
        }

        char *dataPtr = alloc->alloc(r, f);
        if(!diskData) { diskData = dataPtr; }

        size_t dataSz = file->read(diskData, diskLength);
        if(dataSz < diskLength)
            raise<IOError>("short record: got %1% bytes of %2% (%3%:%4%)",
                           dataSz, diskLength, file->getName(), pos);

        if(isCompressed) {
            lzo1x_decompress_safe((unsigned char*)diskData, diskLength, (unsigned char*)dataPtr, &uncompressedSize, NULL);
        }

        return true;
    }
    catch(Exception const & ex) {
        raise<IOError>("failed to get record (%1%:%2%): %3%",
                       file->getName(), pos, ex.what());
    }
}

std::string FileInput::getName() const
{
    using boost::format;

    if(file)
        return (format("%s#%s") % file->getName() % file->tell()).str();
    else
        return std::string("null");
}

FileInput::handle_t FileInput::make(file_t const & fp)
{
    alloc_t alloc(new RecordBufferAllocator());
    handle_t h(new FileInput(fp, VEGA_SPEC, alloc));
    return h;
}

FileInput::handle_t FileInput::make(file_t const & fp, alloc_t const & alloc)
{
    handle_t h(new FileInput(fp, VEGA_SPEC, alloc));
    return h;
}

FileInput::handle_t FileInput::make(file_t const & fp, size_t allocSz)
{
    alloc_t alloc(new RecordBufferAllocator(allocSz));
    handle_t h(new FileInput(fp, VEGA_SPEC, alloc));
    return h;
}


//----------------------------------------------------------------------------
// FileOutput
//----------------------------------------------------------------------------
FileOutput::FileOutput(file_t const & file, HeaderSpec const * spec) :
    file(file), spec(spec), hdrBuf(0)
{
    allocHeaderBuf(hdrBuf, spec);
}

FileOutput::~FileOutput()
{
    delete[] hdrBuf;
}

FileOutput::FileOutput(FileOutput const & o) :
    file(file), spec(spec), hdrBuf(0)
{
    allocHeaderBuf(hdrBuf, spec);
}

FileOutput const & FileOutput::operator=(FileOutput const & o)
{
    file = o.file;
    spec = o.spec;
    allocHeaderBuf(hdrBuf, spec);
    return *this;
}

void FileOutput::setFile(file_t const & f)
{
    file = f;
}

void FileOutput::setHeaderSpec(HeaderSpec const * s)
{
    spec = s;
    allocHeaderBuf(hdrBuf, spec);
}

void FileOutput::flush()
{
    assert(file);
    file->flush();
}

void FileOutput::put(Record const & r)
{
    assert(file);
    assert(spec);
    assert(hdrBuf);
    
    HeaderSpec::Fields f(r);

    const char *outputData = r.getData();
    lzo_uint originalSize = (lzo_uint)f.length;
    lzo_uint compressedSize = originalSize;
    bool isCompressed = r.getFlags() & HeaderSpec::LZO_COMPRESSED;

    if(isCompressed) {
        // In the worst case, LZO may bloat the input data instead of compressing
        // Docs say an extra 16 bytes per 1024 bytes of input should be safe
        size_t bufferSize = originalSize + 16*(1+originalSize/1024);
        lzoBuffer.reserve(bufferSize);
        char *compressedData = &lzoBuffer[0];
        lzo1x_1_compress((unsigned char*)outputData, originalSize, (unsigned char*)compressedData, &compressedSize, lzoWorkingMemory);
        if(compressedSize < originalSize) {
            f.length = compressedSize;
            outputData = compressedData;
        } else {
            isCompressed = false;
            f.flags ^= HeaderSpec::LZO_COMPRESSED;
        }
    }
    
    spec->serialize(f, hdrBuf);
    if(!file->write(hdrBuf, spec->headerSize(), 1))
        raise<IOError>("couldn't write header for Record %s to '%s'",
                       r.toString(), file->getName());

    if(isCompressed) { file->write(&originalSize, sizeof(lzo_uint)); }

    size_t dataSz = file->write(outputData, f.length);
    if(dataSz < f.length)
        raise<IOError>("couldn't write data for Record %s (wrote %d bytes) "
                       "to '%s'", r.toString(), dataSz, file->getName());
}

std::string FileOutput::getName() const
{
    using boost::format;

    if(file)
        return (format("%s#%s") % file->getName() % file->tell()).str();
    else
        return std::string("null");
}

FileOutput::handle_t FileOutput::make(file_t const & fp)
{
    handle_t h(new FileOutput(fp, VEGA_SPEC));
    return h;
}
