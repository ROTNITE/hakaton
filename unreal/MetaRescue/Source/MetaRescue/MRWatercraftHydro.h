#pragma once
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

// Hydrostatic quadrature in metres/m3/kg/Newtons. The generated profile is
// tied to the prepared twin-hull model; it never drives a target Z position.
class FMRWatercraftHydro
{
public:
    double DryMassKg=0,PayloadKg=0,PayloadLimitKg=0,BodyAboveKeelM=0,DeckAboveKeelM=0;
    double BatteryWh=0,MaximumJetThrustN=0,MaximumSpeedMPerSecond=0;
    FString ModelSourceHash;
    TArray<double> SectionX,SectionY;

    bool Read(const TSharedPtr<FJsonObject>& Data)
    {
        Valid=false;Volumes.Empty();SectionX.Empty();SectionY.Empty();
        FString Format,Asset;
        if(!Data||!Data->TryGetStringField(TEXT("format"),Format)||Format!=TEXT("metarescue.watercraft-hydrostatics.v1")||
           !Data->TryGetStringField(TEXT("asset_id"),Asset)||Asset!=TEXT("RescueWaterCatamaran-r1")||
           !Data->TryGetStringField(TEXT("model_source_sha256"),ModelSourceHash)||ModelSourceHash.Len()!=64)return false;
        for(TCHAR C:ModelSourceHash)if(!FChar::IsHexDigit(C))return false;
        if(!Number(Data,TEXT("height_step_m"),Step,.005,.05)||!Number(Data,TEXT("sealed_top_m"),Top,.3,.8)||
           !Number(Data,TEXT("dry_mass_kg"),DryMassKg,200,1200)||!Number(Data,TEXT("person_and_stretcher_mass_kg"),PayloadKg,40,200)||
           !Number(Data,TEXT("payload_limit_kg"),PayloadLimitKg,PayloadKg,300)||
           !Number(Data,TEXT("body_origin_above_keel_m"),BodyAboveKeelM,.2,.8)||
           !Number(Data,TEXT("cargo_deck_above_keel_m"),DeckAboveKeelM,.5,1.4)||
           !Number(Data,TEXT("battery_wh"),BatteryWh,100,10000)||!Number(Data,TEXT("maximum_jet_thrust_n"),MaximumJetThrustN,100,3000)||
           !Number(Data,TEXT("maximum_speed_m_s"),MaximumSpeedMPerSecond,.5,5))return false;
        const TArray<TSharedPtr<FJsonValue>> *X=nullptr,*Y=nullptr,*Rows=nullptr;
        if(!Data->TryGetArrayField(TEXT("section_x_m"),X)||!Data->TryGetArrayField(TEXT("section_y_m"),Y)||
           !Data->TryGetArrayField(TEXT("section_volume_m3"),Rows)||X->Num()!=8||Y->Num()!=8||Rows->Num()!=8)return false;
        const int32 Count=FMath::RoundToInt(Top/Step)+1;
        if(Count<8||Count>161||FMath::Abs((Count-1)*Step-Top)>1.e-8)return false;
        for(int32 I=0;I<8;++I)
        {
            double SX,SY;
            if(!(*X)[I]->TryGetNumber(SX)||!(*Y)[I]->TryGetNumber(SY)||!FMath::IsFinite(SX)||!FMath::IsFinite(SY)||
               FMath::Abs(SX)>2.3||FMath::Abs(SY)<.3||FMath::Abs(SY)>.9||(*Rows)[I]->Type!=EJson::Array)return false;
            SectionX.Add(SX);SectionY.Add(SY);const auto& Curve=(*Rows)[I]->AsArray();if(Curve.Num()!=Count)return false;
            TArray<double> Row;double Previous=0;
            for(int32 J=0;J<Count;++J)
            {
                double V;if(!Curve[J]->TryGetNumber(V)||!FMath::IsFinite(V)||V<Previous||V>1||(J==0&&V!=0))return false;
                Row.Add(V);Previous=V;
            }
            Volumes.Add(MoveTemp(Row));
        }
        Valid=true;
        if(1000*DisplacementM3(Top)<(DryMassKg+PayloadLimitKg)*1.25){Valid=false;return false;}
        return true;
    }

    bool IsValid() const {return Valid;}
    double SectionVolumeM3(int32 I,double HeightAboveKeelM) const
    {
        if(!Valid||!Volumes.IsValidIndex(I)||!FMath::IsFinite(HeightAboveKeelM))return 0;
        const double Index=FMath::Clamp(HeightAboveKeelM,0.,Top)/Step;
        const int32 A=FMath::Min(Volumes[I].Num()-2,FMath::FloorToInt(Index));
        return FMath::Lerp(Volumes[I][A],Volumes[I][A+1],Index-A);
    }
    double DisplacementM3(double HeightAboveKeelM) const
    {double Sum=0;for(int32 I=0;I<Volumes.Num();++I)Sum+=SectionVolumeM3(I,HeightAboveKeelM);return Sum;}
    TOptional<double> EquilibriumDraftM(double MassKg) const
    {
        if(!Valid||!FMath::IsFinite(MassKg)||MassKg<=0||MassKg>DisplacementM3(Top)*1000)return {};
        double Low=0,High=Top;
        for(int32 I=0;I<48;++I){const double Mid=(Low+High)*.5;if(DisplacementM3(Mid)*1000<MassKg)Low=Mid;else High=Mid;}
        return (Low+High)*.5;
    }
private:
    bool Valid=false;
    double Step=0,Top=0;
    TArray<TArray<double>> Volumes;
    static bool Number(const TSharedPtr<FJsonObject>& Data,const TCHAR* Key,double& Value,double Low,double High)
    {return Data->TryGetNumberField(Key,Value)&&FMath::IsFinite(Value)&&Value>=Low&&Value<=High;}
};
