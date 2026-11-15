#include "MRCoreStore.h"
#include "HAL/PlatformFileManager.h"
#include "Misc/Compression.h"
#include "Misc/Crc.h"

namespace
{
void Put(uint8* Out,uint64 Value,int32 Size)
{for(int32 I=0;I<Size;I++)Out[I]=uint8(Value>>(8*I));}
uint64 Get(const uint8* In,int32 Size)
{uint64 Value=0;for(int32 I=0;I<Size;I++)Value|=uint64(In[I])<<(8*I);return Value;}
bool Failed(FString& Error,const TCHAR* Message){Error=Message;return false;}
}

FMRCoreDiskRecords::FMRCoreDiskRecords()=default;
FMRCoreDiskRecords::~FMRCoreDiskRecords()=default;

bool FMRCoreDiskRecords::Open(const FString& Stem,FString& Error)
{
    auto& Files=FPlatformFileManager::Get().GetPlatformFile();
    if(Files.FileExists(*(Stem+TEXT(".records")))||Files.FileExists(*(Stem+TEXT(".index"))))
        return Failed(Error,TEXT("Journal already exists; refusing to overwrite"));
    DataWriter.Reset(Files.OpenWrite(*(Stem+TEXT(".records")),false,true));
    IndexWriter.Reset(Files.OpenWrite(*(Stem+TEXT(".index")),false,true));
    if(!DataWriter||!IndexWriter)return Failed(Error,TEXT("Cannot open journal writers"));
    FileStem=Stem;return true;
}

bool FMRCoreDiskRecords::Append(const TArray<uint8>& Raw,FString& Error)
{
    if(WriteFailed||!DataWriter||!IndexWriter)return Failed(Error,TEXT("Journal is not writable"));
    if(Raw.IsEmpty()||Raw.Num()>MaxRecordBytes)return Failed(Error,TEXT("Journal record exceeds declared size"));
    TArray<uint8> Compressed;const uint8* Data=Raw.GetData();int32 Size=Raw.Num();uint32 Codec=0;
    if(Raw.Num()>=1024)
    {
        int32 Bound=FCompression::CompressMemoryBound(NAME_Zlib,Raw.Num());
        if(Bound<=0)return Failed(Error,TEXT("Cannot obtain compression bound"));
        Compressed.SetNumUninitialized(Bound);
        if(!FCompression::CompressMemory(NAME_Zlib,Compressed.GetData(),Bound,Raw.GetData(),Raw.Num()))
            return Failed(Error,TEXT("Journal compression failed"));
        if(Bound<Size){Data=Compressed.GetData();Size=Bound;Codec=1;}
    }
    if(DataBytes>MaxDataBytes-Size)return Failed(Error,TEXT("Journal disk byte limit reached"));
    uint8 Entry[24];Put(Entry,uint64(DataBytes),8);Put(Entry+8,uint32(Size),4);
    Put(Entry+12,uint32(Raw.Num()),4);Put(Entry+16,FCrc::MemCrc32(Raw.GetData(),Raw.Num()),4);Put(Entry+20,Codec,4);
    if(!DataWriter->Write(Data,Size)||!IndexWriter->Write(Entry,sizeof(Entry)))
    {WriteFailed=true;return Failed(Error,TEXT("Journal write failed; archive is incomplete"));}
    DataBytes+=Size;RawBytes+=Raw.Num();++Count;return true;
}

bool FMRCoreDiskRecords::Read(int64 Index,TArray<uint8>& Raw,FString& Error) const
{
    Raw.Empty();if(Index<0||Index>=Count)return Failed(Error,TEXT("Journal record index out of range"));
    // Windows' Unreal reader caches file size at open. A descriptor from an
    // earlier append cannot seek into the new tail, even after writer Flush.
    if(ReaderVersion!=Count)
    {
        auto& Files=FPlatformFileManager::Get().GetPlatformFile();
        DataReader.Reset();IndexReader.Reset();
        DataReader.Reset(Files.OpenRead(*(FileStem+TEXT(".records")),true));
        IndexReader.Reset(Files.OpenRead(*(FileStem+TEXT(".index")),true));
        if(!DataReader||!IndexReader)return Failed(Error,TEXT("Cannot refresh journal readers"));
        ReaderVersion=Count;
    }
    uint8 Entry[24];
    if(!IndexReader||!DataReader||!IndexReader->Seek(Index*24)||!IndexReader->Read(Entry,sizeof(Entry)))
        return Failed(Error,TEXT("Journal index read failed"));
    const uint64 Offset=Get(Entry,8),Size=Get(Entry+8,4),RawSize=Get(Entry+12,4),Codec=Get(Entry+20,4);
    if(!Size||!RawSize||Size>MaxRecordBytes||RawSize>MaxRecordBytes||Codec>1||
       Offset>uint64(DataBytes)||Size>uint64(DataBytes)-Offset||(Codec==0&&Size!=RawSize))
        return Failed(Error,TEXT("Corrupt journal index"));
    TArray<uint8> Stored;Stored.SetNumUninitialized(int32(Size));
    if(!DataReader->Seek(int64(Offset))||!DataReader->Read(Stored.GetData(),Size))
        return Failed(Error,TEXT("Journal record read failed"));
    if(Codec==0)Raw=MoveTemp(Stored);
    else
    {
        Raw.SetNumUninitialized(int32(RawSize));
        if(!FCompression::UncompressMemory(NAME_Zlib,Raw.GetData(),int64(RawSize),Stored.GetData(),int64(Size)))
            return Failed(Error,TEXT("Journal decompression failed"));
    }
    if(FCrc::MemCrc32(Raw.GetData(),Raw.Num())!=uint32(Get(Entry+16,4)))
        return Failed(Error,TEXT("Journal record CRC mismatch"));
    return true;
}

bool FMRCoreDiskRecords::Flush(FString& Error)
{
    if(WriteFailed||!DataWriter||!IndexWriter||!DataWriter->Flush(true)||!IndexWriter->Flush(true))
    {WriteFailed=true;return Failed(Error,TEXT("Journal flush failed; archive is incomplete"));}
    return true;
}
