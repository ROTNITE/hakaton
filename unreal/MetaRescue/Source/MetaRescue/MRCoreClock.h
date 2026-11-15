#pragma once
#include "CoreMinimal.h"

// Fixed maximum execution quantum, split at known delivery/event/sample times.
// Only a completed physics frame advances this clock; getters never advance it.
class FMRCoreClock
{
public:
    static constexpr double Quantum=1./60.,Epsilon=1.e-9;
    void Reset(){Elapsed=StepEnd=0;Frames=0;}
    void BeginStep(double Horizon){StepEnd=FMath::Min(Elapsed+1.,Horizon);}
    double Time() const {return Elapsed;}
    bool StepFinished() const {return Elapsed>=StepEnd-Epsilon;}
    int64 ExecutedFrames() const {return Frames;}
    double NextDelta(const TArray<double>& Boundaries) const
    {
        double Delta=FMath::Min(Quantum,StepEnd-Elapsed);
        for(double At:Boundaries)if(At>Elapsed+Epsilon)Delta=FMath::Min(Delta,At-Elapsed);
        return Delta;
    }
    bool Advance(double Delta)
    {
        if(!FMath::IsFinite(Delta)||Delta<=0||Delta>Quantum+Epsilon||Elapsed+Delta>StepEnd+Epsilon)return false;
        Elapsed+=Delta;if(StepFinished())Elapsed=StepEnd;++Frames;return true;
    }
private:
    double Elapsed=0,StepEnd=0;
    int64 Frames=0;
};
