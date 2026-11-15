#pragma once
#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "MRFilmSubsystem.generated.h"

class ACameraActor;
class AMRAgent;

struct FMRFilmKey
{
    double U=0;
    FVector Eye=FVector::ZeroVector,Look=FVector::ZeroVector;
    double Fov=48;
};

struct FMRFilmShot
{
    FString Id,Follow;
    int32 Frames=0,WaitFrames=0,WaitForDelivered=0;
    double WaitUntil=-1;
    bool HeadingSpace=false,CollisionTest=false;
    TArray<FMRFilmKey> Keys;
};

/** Opt-in presentation recorder. Never issues commands or changes the mission. */
UCLASS()
class METARESCUE_API UMRFilmSubsystem : public UTickableWorldSubsystem
{
    GENERATED_BODY()
public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Tick(float DeltaTime) override;
    virtual TStatId GetStatId() const override;
    virtual bool IsTickableWhenPaused() const override {return true;}
    virtual void Deinitialize() override;
private:
    UPROPERTY() TObjectPtr<ACameraActor> FilmCamera;
    TArray<FMRFilmShot> Shots;
    FString Output,PendingFile,PendingRow;
    int32 Fps=30,Warmup=120,TickNumber=0,ShotIndex=0,ShotFrame=0,Waiting=0,Written=0;
    bool Ready=false,Pending=false,Finishing=false,Failed=false,AnchorReady=false;
    bool ExitOnFinish=true;
    double CadenceClock=0;
    FVector Anchor=FVector::ZeroVector;
    FDelegateHandle ProcessedHandle;
    bool ReadPlan(const FString& Path);
    void ApplyCamera(const FMRFilmShot& Shot,double U,float DeltaTime);
    void ScreenshotProcessed();
    void Fail(const FString& Reason);
    void Finish();
};
