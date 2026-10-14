// Copyright (c) 2026 Native Workbench contributors. MIT license.
// STAR uses external read/SAM chunk arrays. basic_stringbuf::pubsetbuf is
// implementation-defined and libc++ ignores it. This bounded, non-owning
// streambuf gives both supported standard libraries the required semantics.
#ifndef WORKBENCH_BUFFER_STREAM_H
#define WORKBENCH_BUFFER_STREAM_H
#include <istream>
#include <ostream>
#include <streambuf>
#include <limits>
#include <stdexcept>
#include <algorithm>

class WorkbenchBuffer : public std::streambuf {
    char *data_;
    std::size_t capacity_, size_;
    bool input_;
    void putPosition(off_type position) {
        setp(data_, data_ + capacity_);
        while (position > 0) {
            const int step = static_cast<int>(std::min<off_type>(position, std::numeric_limits<int>::max()));
            pbump(step);
            position -= step;
        }
    }
protected:
    pos_type seekoff(off_type offset, std::ios_base::seekdir direction,
                     std::ios_base::openmode mode) override {
        const auto wanted = input_ ? std::ios_base::in : std::ios_base::out;
        if (mode != wanted) return pos_type(off_type(-1));
        const off_type length = static_cast<off_type>(input_ ? size_ : capacity_);
        off_type origin;
        if (direction == std::ios_base::beg) origin = 0;
        else if (direction == std::ios_base::end) origin = length;
        else if (direction == std::ios_base::cur)
            origin = input_ ? gptr() - eback() : pptr() - pbase();
        else return pos_type(off_type(-1));
        // Bounds checks precede addition, so even extreme offsets cannot overflow.
        if (offset < -origin || offset > length - origin) return pos_type(off_type(-1));
        const off_type position = origin + offset;
        if (input_) setg(data_, data_ + position, data_ + size_);
        else putPosition(position);
        return pos_type(position);
    }
    pos_type seekpos(pos_type position, std::ios_base::openmode mode) override {
        return seekoff(static_cast<off_type>(position), std::ios_base::beg, mode);
    }
public:
    WorkbenchBuffer(char *data, std::size_t capacity, bool input)
        : data_(data), capacity_(capacity), size_(0), input_(input) {
        if (!data || capacity > static_cast<std::size_t>(std::numeric_limits<off_type>::max()))
            throw std::length_error("Invalid STAR chunk buffer capacity");
        if (input_) setg(data_, data_, data_);
        else setp(data_, data_ + capacity_);
    }
    void inputSize(std::size_t size) {
        if (!input_ || size > capacity_) throw std::length_error("STAR input chunk exceeds its buffer");
        size_ = size;
        setg(data_, data_, data_ + size_);
    }
};

class WorkbenchInputStream : public std::istream {
    WorkbenchBuffer buffer_;
public:
    WorkbenchInputStream(char *data, std::size_t capacity)
        : std::istream(nullptr), buffer_(data, capacity, true) { rdbuf(&buffer_); }
    void inputSize(std::size_t size) { buffer_.inputSize(size); clear(); }
};

class WorkbenchOutputStream : public std::ostream {
    WorkbenchBuffer buffer_;
public:
    WorkbenchOutputStream(char *data, std::size_t capacity)
        : std::ostream(nullptr), buffer_(data, capacity, false) { rdbuf(&buffer_); }
};
#endif
