#pragma once
#include "CoreMinimal.h"

class IFileHandle;

// Sequential compressed UTF-8 records, random-access disk index, no resident history.
// The 24-byte index entries are explicitly little endian (offset, sizes, CRC, codec).
class FMRCoreDiskRecords
{
public:
    FMRCoreDiskRecords();
    ~FMRCoreDiskRecords();
    static constexpr int32 MaxRecordBytes=32*1024*1024;
    static constexpr int64 MaxDataBytes=1ll<<40;
    bool Open(const FString& Stem,FString& Error);
    bool Append(const TArray<uint8>& Raw,FString& Error);
    bool Read(int64 Index,TArray<uint8>& Raw,FString& Error) const;
    bool Flush(FString& Error);
    int64 Num() const {return Count;}
    int64 Bytes() const {return DataBytes;}
    int64 UncompressedBytes() const {return RawBytes;}
private:
    friend class FMRDiskRecordsTest;
    int64 Count=0,DataBytes=0,RawBytes=0;
    bool WriteFailed=false;
    FString FileStem;
    TUniquePtr<IFileHandle> DataWriter,IndexWriter;
    mutable int64 ReaderVersion=-1;
    mutable TUniquePtr<IFileHandle> DataReader,IndexReader;
};
