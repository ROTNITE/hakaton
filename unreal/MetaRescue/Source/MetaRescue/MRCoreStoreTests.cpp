#if WITH_DEV_AUTOMATION_TESTS
#include "MRCoreStore.h"
#include "HAL/PlatformFileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRDiskRecordsTest,"MetaRescue.Core.DiskRecords",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRDiskRecordsTest::RunTest(const FString&)
{
    FString Root=FPlatformMisc::GetEnvironmentVariable(TEXT("METARESCUE_OUTPUT"));if(Root.IsEmpty())Root=TEXT("D:/MetaRescue-output");
    const FString Directory=Root/TEXT("store-tests")/FGuid::NewGuid().ToString(EGuidFormats::Digits);
    auto& Files=FPlatformFileManager::Get().GetPlatformFile();TestTrue(TEXT("test directory"),Files.CreateDirectoryTree(*Directory));
    FMRCoreDiskRecords Store;FString Error;TestTrue(TEXT("open store"),Store.Open(Directory/TEXT("test"),Error));
    TArray<TArray<uint8>> Expected;
    for(int32 I=0;I<600;I++)
    {
        TArray<uint8> Raw;Raw.SetNumUninitialized(I%2?17:6000);
        for(int32 J=0;J<Raw.Num();J++)Raw[J]=uint8((I+J%7)%251);
        TestTrue(TEXT("append"),Store.Append(Raw,Error));Expected.Add(MoveTemp(Raw));
    }
    TestTrue(TEXT("flush"),Store.Flush(Error));TestEqual(TEXT("records"),Store.Num(),int64(600));
    TestTrue(TEXT("compressed history on disk"),Store.Bytes()<Store.UncompressedBytes()/3);
    for(int32 I=599;I>=0;I--)
    {TArray<uint8> Raw;TestTrue(TEXT("reverse read"),Store.Read(I,Raw,Error));TestTrue(TEXT("exact bytes"),Raw==Expected[I]);}
    TArray<uint8> Raw;TestFalse(TEXT("negative cursor"),Store.Read(-1,Raw,Error));
    TestFalse(TEXT("past end"),Store.Read(600,Raw,Error));TestFalse(TEXT("empty record"),Store.Append({},Error));
    // Windows denies a second writer. Mutate via the test's friend descriptor;
    // reopen the reader to exclude an old buffered read from this fault test.
    TestTrue(TEXT("seek final byte"),Store.DataWriter->Seek(Store.Bytes()-1));uint8 Bad=255;
    TestTrue(TEXT("write corrupt byte"),Store.DataWriter->Write(&Bad,1));Store.DataWriter->Flush(true);
    Store.ReaderVersion=-1;
    TestFalse(TEXT("CRC rejects changed data"),Store.Read(599,Raw,Error));
    TestTrue(TEXT("explicit CRC reason"),Error.Contains(TEXT("CRC")));
    FMRCoreDiskRecords Again;TestFalse(TEXT("never overwrite an old store"),Again.Open(Directory/TEXT("test"),Error));
    return true;
}
#endif
