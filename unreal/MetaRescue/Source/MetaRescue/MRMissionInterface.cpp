#include "MRMissionInterface.h"
#include "MRMissionSession.h"
#include "MRCoreValues.h"
#include "MRCoreRuntime.h"
#include "MRDisplayTrace.h"
#include "MRWorld.h"
#include "MRCameraPawn.h"
#include "MRAgent.h"
#include "EngineUtils.h"
#include "Framework/Application/SlateApplication.h"
#include "Styling/CoreStyle.h"
#include "Brushes/SlateColorBrush.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SSeparator.h"
#include "Widgets/Layout/SSpacer.h"
#include "Widgets/SOverlay.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Input/SComboButton.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SNumericEntryBox.h"
#include "Widgets/Text/STextBlock.h"

using namespace MRCoreValues;

namespace
{
const FLinearColor Ink(.89f,.92f,.88f),Muted(.53f,.59f,.55f),Accent(.75f,.86f,.43f),Warning(.95f,.56f,.35f);
const FSlateColorBrush Background(FLinearColor(.028f,.036f,.031f,.98f));
const FSlateColorBrush Panel(FLinearColor(.047f,.059f,.050f,.96f));
FText Tx(const FString& S){return FText::FromString(S);}
FSlateFontInfo Font(int32 Size=13,bool Bold=false){return FCoreStyle::GetDefaultFontStyle(Bold?TEXT("Bold"):TEXT("Regular"),Size);}

struct FInterfaceStyle
{
    FButtonStyle Normal,Primary;
    FInterfaceStyle()
    {
        Normal=FCoreStyle::Get().GetWidgetStyle<FButtonStyle>(TEXT("Button"));
        Normal.SetNormal(FSlateColorBrush(FLinearColor(.075f,.094f,.077f))).SetHovered(FSlateColorBrush(FLinearColor(.14f,.18f,.12f)))
            .SetPressed(FSlateColorBrush(FLinearColor(.20f,.25f,.16f))).SetNormalForeground(Ink).SetHoveredForeground(Ink).SetPressedForeground(Ink);
        Primary=Normal;Primary.SetNormal(FSlateColorBrush(Accent)).SetHovered(FSlateColorBrush(FLinearColor(.85f,.95f,.57f)))
            .SetNormalForeground(FLinearColor(.045f,.065f,.025f)).SetHoveredForeground(FLinearColor(.045f,.065f,.025f));
    }
};
FInterfaceStyle& Styles(){static FInterfaceStyle S;return S;}

using Choices=TArray<TPair<FString,FString>>;

class SMRMissionInterface : public SCompoundWidget
{
public:
    SLATE_BEGIN_ARGS(SMRMissionInterface){} SLATE_ARGUMENT(UMRMissionSession*,Session) SLATE_END_ARGS()
    void Construct(const FArguments& Args)
    {
        Session=Args._Session;
        ChildSlot[SNew(SOverlay)
            +SOverlay::Slot().HAlign(HAlign_Fill).VAlign(VAlign_Top).Padding(20)[SNew(SBox).Visibility_Lambda([this]{return MissionVisibility();})[BuildHeader()]]
            +SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Bottom).Padding(20,0,0,86)
                [SNew(SBox).WidthOverride(220).Visibility_Lambda([this]{return MissionVisibility();})[BuildLayers()]]
            +SOverlay::Slot().HAlign(HAlign_Right).VAlign(VAlign_Top).Padding(0,108,20,90)
                [SNew(SBox).WidthOverride(342).Visibility_Lambda([this]{return !Session->SetupOpen&&Session->InspectorOpen?EVisibility::Visible:EVisibility::Collapsed;})[BuildInspector()]]
            +SOverlay::Slot().HAlign(HAlign_Fill).VAlign(VAlign_Bottom).Padding(20)
                [SNew(SBox).Visibility_Lambda([this]{return MissionVisibility();})[BuildControls()]]
            +SOverlay::Slot().Padding(20).HAlign(HAlign_Fill).VAlign(VAlign_Fill)
                [SNew(SBox).Visibility_Lambda([this]{return Session->SetupOpen?EVisibility::Visible:EVisibility::Collapsed;})[BuildSetup()]]
            +SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)
                [SNew(SBox).WidthOverride(570).Visibility_Lambda([this]{return !Session->SetupOpen&&Session->Busy()?EVisibility::HitTestInvisible:EVisibility::Collapsed;})
                    [SNew(SBorder).BorderImage(&Panel).Padding(24)
                        [SNew(SVerticalBox)+SVerticalBox::Slot().AutoHeight()[LabelDynamic([this]{return Session->StageLabel();},20,Accent)]
                            +SVerticalBox::Slot().AutoHeight().Padding(0,12,0,0)[LabelDynamic([this]{return Session->Message;},13,Muted)]]]]
        ];
    }
private:
    UMRMissionSession* Session=nullptr;
    FString PresetTitle=TEXT("Мой спасательный район");
    EVisibility MissionVisibility() const {return Session->SetupOpen?EVisibility::Collapsed:EVisibility::Visible;}
    Object Group(const FString& Name) const
    {
        if(Name==TEXT("probabilities"))return Session->Configuration->GetObjectField(TEXT("settings"))->GetObjectField(Name);
        return Session->Configuration->GetObjectField(Name);
    }
    TSharedRef<SWidget> Label(const FString& Text,int32 Size=13,FLinearColor Color=Ink) const
    {return SNew(STextBlock).Text(Tx(Text)).Font(Font(Size)).ColorAndOpacity(Color).AutoWrapText(true);}
    TSharedRef<SWidget> LabelDynamic(TFunction<FString()> Getter,int32 Size=13,FLinearColor Color=Ink) const
    {return SNew(STextBlock).Text_Lambda([Getter]{return Tx(Getter());}).Font(Font(Size)).ColorAndOpacity(Color).AutoWrapText(true);}
    TSharedRef<SWidget> Button(const FString& Name,TFunction<void()> Action,TAttribute<bool> Enabled=true,bool Primary=false)
    {return SNew(SButton).ButtonStyle(Primary?&Styles().Primary:&Styles().Normal).ContentPadding(FMargin(15,10)).IsEnabled(Enabled)
        .OnClicked_Lambda([Action]{Action();return FReply::Handled();})[SNew(STextBlock).Text(Tx(Name)).Font(Font(12,true))];}
    TSharedRef<SWidget> Row(const FString& Name,TSharedRef<SWidget> Value)
    {return SNew(SHorizontalBox)+SHorizontalBox::Slot().FillWidth(1).VAlign(VAlign_Center).Padding(0,0,12,0)[Label(Name,12)]
        +SHorizontalBox::Slot().FillWidth(1.05f).VAlign(VAlign_Center)[Value];}
    TSharedRef<SWidget> Number(const FString& Section,const FString& Key,double Minimum,double Maximum,bool Integer=false)
    {
        return SNew(SNumericEntryBox<double>).Font(Font(12)).AllowSpin(false).MinValue(Minimum).MaxValue(Maximum)
            .MinFractionalDigits(0).MaxFractionalDigits(Integer?0:3)
            .Value_Lambda([this,Section,Key]()->TOptional<double>{double Value=0;Group(Section)->TryGetNumberField(Key,Value);return Value;})
            .OnValueCommitted_Lambda([this,Section,Key,Minimum,Maximum,Integer](double Value,ETextCommit::Type)
            {if(FMath::IsFinite(Value))Group(Section)->SetNumberField(Key,Integer?FMath::RoundToDouble(FMath::Clamp(Value,Minimum,Maximum)):FMath::Clamp(Value,Minimum,Maximum));});
    }
    TSharedRef<SWidget> Combo(const FString& Section,const FString& Key,const Choices& Options,TFunction<void(const FString&)> Changed={})
    {
        return SNew(SComboButton).ButtonStyle(&Styles().Normal).ContentPadding(FMargin(10,7)).ForegroundColor(Ink)
            .OnGetMenuContent_Lambda([this,Section,Key,Options,Changed]()->TSharedRef<SWidget>
            {
                auto Menu=SNew(SVerticalBox);
                for(const auto& Option:Options)Menu->AddSlot().AutoHeight()[Button(Option.Value,[this,Section,Key,Option,Changed]
                    {Group(Section)->SetStringField(Key,Option.Key);if(Changed)Changed(Option.Key);FSlateApplication::Get().DismissAllMenus();})];
                return SNew(SBorder).BorderImage(&Panel).Padding(4)[SNew(SBox).MaxDesiredHeight(440)[SNew(SScrollBox)+SScrollBox::Slot()[Menu]]];
            })
            .ButtonContent()[LabelDynamic([this,Section,Key,Options]
            {const FString Value=Text(Group(Section),Key);for(const auto& Option:Options)if(Option.Key==Value)return Option.Value;return Value;},12)];
    }
    TSharedRef<SWidget> Check(const FString& Section,const FString& Key,const FString& Name)
    {return SNew(SCheckBox).IsChecked_Lambda([this,Section,Key]{return Group(Section)->GetBoolField(Key)?ECheckBoxState::Checked:ECheckBoxState::Unchecked;})
        .OnCheckStateChanged_Lambda([this,Section,Key](ECheckBoxState Value){Group(Section)->SetBoolField(Key,Value==ECheckBoxState::Checked);})[Label(Name,12)];}
    TSharedRef<SWidget> Toggle(bool UMRMissionSession::* Member,const FString& Name)
    {return SNew(SCheckBox).IsChecked_Lambda([this,Member]{return Session->*Member?ECheckBoxState::Checked:ECheckBoxState::Unchecked;})
        .OnCheckStateChanged_Lambda([this,Member,Name](ECheckBoxState Value){Session->*Member=Value==ECheckBoxState::Checked;Session->LogAction(Name);})[Label(Name,12)];}
    void Add(TSharedRef<SVerticalBox> Column,const FString& Name,TSharedRef<SWidget> Value)
    {Column->AddSlot().AutoHeight().Padding(0,6)[Row(Name,Value)];}
    void Section(TSharedRef<SVerticalBox> Column,const FString& Title,const FString& Note=TEXT(""))
    {Column->AddSlot().AutoHeight().Padding(0,18,0,8)[Label(Title,17,Accent)];if(!Note.IsEmpty())Column->AddSlot().AutoHeight().Padding(0,0,0,8)[Label(Note,11,Muted)];}
    void ResetEvents(bool Zero=false)
    {
        const bool V3=Text(Group(TEXT("settings")),TEXT("event_profile"))==TEXT("v3");
        auto Probabilities=V3?Obj({{TEXT("collapse"),Num(12)},{TEXT("fire"),Num(12)},{TEXT("flood"),Num(10)},{TEXT("mud"),Num(14)},
            {TEXT("road_damage"),Num(14)},{TEXT("smoke"),Num(15)},{TEXT("low_visibility"),Num(12)},{TEXT("new_target"),Num(20)}}):
            Obj({{TEXT("collapse"),Num(20)},{TEXT("fire"),Num(18)},{TEXT("flood"),Num(12)},{TEXT("mud"),Num(25)},
                {TEXT("road_damage"),Num(23)},{TEXT("smoke"),Num(28)},{TEXT("appearance"),Num(30)}});
        if(Zero)for(auto& Pair:Probabilities->Values)Pair.Value=Num(0);
        Group(TEXT("settings"))->SetObjectField(TEXT("probabilities"),Probabilities);
    }
    TSharedRef<SWidget> BuildSetup()
    {
        auto World=SNew(SVerticalBox),Algorithms=SNew(SVerticalBox),Events=SNew(SVerticalBox);
        Section(World,TEXT("01 / Район и участники"),TEXT("Физический масштаб: 10 м на клетку. Размеры моделей сохраняются."));
        auto Sizes=SNew(SComboButton).ButtonStyle(&Styles().Normal).ContentPadding(FMargin(10,7)).ForegroundColor(Ink)
            .OnGetMenuContent_Lambda([this]()->TSharedRef<SWidget>{auto Menu=SNew(SVerticalBox);for(int32 Size:{25,35,45,55,65,75,100,125,150})
                Menu->AddSlot().AutoHeight()[Button(FString::Printf(TEXT("%d × %d · %d м"),Size,Size,Size*10),[this,Size]{Group(TEXT("settings"))->SetNumberField(TEXT("map_size"),Size);FSlateApplication::Get().DismissAllMenus();})];return Menu;})
            .ButtonContent()[LabelDynamic([this]{const int32 N=Group(TEXT("settings"))->GetIntegerField(TEXT("map_size"));return FString::Printf(TEXT("%d × %d · %d м"),N,N,N*10);},12)];
        Add(World,TEXT("Размер"),Sizes);
        Add(World,TEXT("Seed мира"),Number(TEXT("settings"),TEXT("seed"),0,999999999,true));
        Add(World,TEXT("Условия"),Combo(TEXT("settings"),TEXT("preset"),{{TEXT("open"),TEXT("S1 · Открытая местность")},{TEXT("urban"),TEXT("S2 · Город")},
            {TEXT("clusters"),TEXT("S3 · Группы целей")},{TEXT("scarce"),TEXT("S4 · Дефицит")},{TEXT("uncertain"),TEXT("S5 · Неопределённость")},{TEXT("dynamic"),TEXT("S6 · Динамика")}}));
        Add(World,TEXT("Окружение"),Combo(TEXT("settings"),TEXT("layout"),{{TEXT("rescue_quarter"),TEXT("Детальный квартал")},{TEXT("generated_city"),TEXT("Городской район")}}));
        Add(World,TEXT("Дроны разведки"),Number(TEXT("settings"),TEXT("scouts"),1,48,true));
        Add(World,TEXT("Эвакуаторы"),Number(TEXT("settings"),TEXT("rescuers"),1,40,true));
        Add(World,TEXT("Люди при старте"),Number(TEXT("settings"),TEXT("people"),3,600,true));
        Add(World,TEXT("Горизонт, с"),Number(TEXT("settings"),TEXT("horizon"),1,86400));
        World->AddSlot().AutoHeight().Padding(0,10)[Check(TEXT("settings"),TEXT("competition"),TEXT("Конкурсный участок · все 8 категорий"))];
        Section(World,TEXT("Ресурсы"));
        Add(World,TEXT("Профиль"),Combo(TEXT("settings"),TEXT("resource_profile"),{{TEXT("unlimited"),TEXT("Исследование · без лимита")},{TEXT("contest"),TEXT("Конкурс · конечный заряд")}}));
        Add(World,TEXT("Батарея ровера, Wh"),Number(TEXT("settings"),TEXT("ground_battery_wh"),1,10000));
        Add(World,TEXT("Батарея дрона, Wh"),Number(TEXT("settings"),TEXT("aerial_battery_wh"),1,10000));
        Add(World,TEXT("Начальный заряд, 0–1"),Number(TEXT("settings"),TEXT("initial_battery_fraction"),0,1));
        Add(World,TEXT("Резерв, 0–0,75"),Number(TEXT("settings"),TEXT("energy_reserve_fraction"),0,.75));

        Section(Algorithms,TEXT("02 / Управление"),TEXT("Два независимых оптимизатора: разведка и эвакуация."));
        Add(Algorithms,TEXT("Алгоритмы"),Combo(TEXT("controller"),TEXT("policy"),{{TEXT("nsga2_nsga2"),TEXT("NSGA-II ×2")},{TEXT("greedy_greedy"),TEXT("Greedy + Greedy")},
            {TEXT("frontier_local"),TEXT("Frontier + Local")},{TEXT("nsga2_greedy"),TEXT("NSGA-II + Greedy")},{TEXT("greedy_nsga2"),TEXT("Greedy + NSGA-II")},
            {TEXT("fixed_workflow"),TEXT("Фиксированный workflow")},{TEXT("local_reactive"),TEXT("Локальный реактивный")}},[this](const FString& Value)
            {if(Value==TEXT("fixed_workflow")||Value==TEXT("local_reactive")){Group(TEXT("controller"))->SetStringField(TEXT("ai_mode"),TEXT("OFF"));Group(TEXT("controller"))->SetBoolField(TEXT("contest_coordination"),false);}}));
        Add(Algorithms,TEXT("Seed оптимизатора"),Number(TEXT("controller"),TEXT("optimizer_seed"),0,999999999,true));
        Add(Algorithms,TEXT("Scout · популяция"),Number(TEXT("controller"),TEXT("scout_population"),4,256,true));
        Add(Algorithms,TEXT("Scout · поколения"),Number(TEXT("controller"),TEXT("scout_generations"),1,256,true));
        Add(Algorithms,TEXT("Rescue · популяция"),Number(TEXT("controller"),TEXT("rescue_population"),4,256,true));
        Add(Algorithms,TEXT("Rescue · поколения"),Number(TEXT("controller"),TEXT("rescue_generations"),1,256,true));
        Algorithms->AddSlot().AutoHeight().Padding(0,10)[Check(TEXT("controller"),TEXT("contest_coordination"),TEXT("Коалиции и конкурсные сценарии"))];
        Section(Algorithms,TEXT("Global + Local AI"));
        Add(Algorithms,TEXT("Режим"),Combo(TEXT("controller"),TEXT("ai_mode"),{{TEXT("OFF"),TEXT("OFF · алгоритмы")},{TEXT("MOCK"),TEXT("MOCK · детерминированный")},{TEXT("LIVE"),TEXT("LIVE · DeepSeek")}},
            [this](const FString& Value){if(Value==TEXT("LIVE"))Group(TEXT("controller"))->SetBoolField(TEXT("realtime"),true);}));
        Add(Algorithms,TEXT("Область AI"),Combo(TEXT("controller"),TEXT("ai_scope"),{{TEXT("global_local"),TEXT("Global + каждый Local")},{TEXT("global"),TEXT("Только Global")}}));
        Algorithms->AddSlot().AutoHeight().Padding(0,8)[LabelDynamic([this]{return KeyStatus();},11,Muted)];
        Algorithms->AddSlot().AutoHeight().Padding(0,10)[Check(TEXT("controller"),TEXT("realtime"),TEXT("Реальное течение времени"))];
        Algorithms->AddSlot().AutoHeight()[Label(TEXT("LIVE требует реального времени. Наличие ключа и успешный ответ API отображаются отдельно."),11,Muted)];

        Section(Events,TEXT("03 / События и связь"));
        Add(Events,TEXT("Модель событий"),Combo(TEXT("settings"),TEXT("event_profile"),{{TEXT("v052"),TEXT("v0.5.2 · 7 событий / 80 с")},{TEXT("v3"),TEXT("v3 · 8 событий / 30 с")}},[this](const FString&){ResetEvents();}));
        const Choices Kinds={{TEXT("collapse"),TEXT("Обрушение, %")},{TEXT("fire"),TEXT("Пожар, %")},{TEXT("flood"),TEXT("Затопление, %")},{TEXT("mud"),TEXT("Грязь, %")},
            {TEXT("road_damage"),TEXT("Повреждение дороги, %")},{TEXT("smoke"),TEXT("Дым, %")},{TEXT("low_visibility"),TEXT("Плохая видимость, %")},
            {TEXT("appearance"),TEXT("Поздняя цель, %")},{TEXT("new_target"),TEXT("Поздняя цель, %")}};
        for(const auto& Kind:Kinds)Events->AddSlot().AutoHeight().Padding(0,6)
            [SNew(SBox).Visibility_Lambda([this,Kind]{return Group(TEXT("probabilities"))->HasField(Kind.Key)?EVisibility::Visible:EVisibility::Collapsed;})
                [Row(Kind.Value,Number(TEXT("probabilities"),Kind.Key,0,100))]];
        Events->AddSlot().AutoHeight().Padding(0,8)[SNew(SHorizontalBox)
            +SHorizontalBox::Slot().FillWidth(1).Padding(0,0,6,0)[Button(TEXT("Без событий"),[this]{ResetEvents(true);})]
            +SHorizontalBox::Slot().FillWidth(1)[Button(TEXT("Сбросить %"),[this]{ResetEvents();})]];
        Section(Events,TEXT("Сенсоры и сеть"));
        Add(Events,TEXT("Надёжность, 0–1"),Number(TEXT("settings"),TEXT("sensor_reliability"),0,1));
        Add(Events,TEXT("Дальность связи, м"),Number(TEXT("settings"),TEXT("communication_range_m"),5,10000));
        Add(Events,TEXT("Задержка звена, с"),Number(TEXT("settings"),TEXT("communication_latency_s"),0,60));
        Add(Events,TEXT("Потери пакетов, 0–1"),Number(TEXT("settings"),TEXT("communication_loss"),0,1));

        return SNew(SBorder).BorderImage(&Background).Padding(26)
            [SNew(SVerticalBox)
                +SVerticalBox::Slot().AutoHeight()[SNew(SHorizontalBox)
                    +SHorizontalBox::Slot().FillWidth(1)[SNew(SVerticalBox)
                        +SVerticalBox::Slot().AutoHeight()[Label(TEXT("META / RESCUE"),12,Accent)]
                        +SVerticalBox::Slot().AutoHeight().Padding(0,7)[Label(TEXT("Подготовка миссии"),30)]
                        +SVerticalBox::Slot().AutoHeight()[Label(TEXT("Настройте район, участников и управление. Проверка размещения выполнится перед загрузкой."),13,Muted)]]
                    +SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[BuildPresets()]]
                +SVerticalBox::Slot().AutoHeight().Padding(0,18,0,0)[SNew(SSeparator).ColorAndOpacity(FLinearColor(.16f,.19f,.16f))]
                +SVerticalBox::Slot().FillHeight(1)[SNew(SScrollBox)+SScrollBox::Slot()
                    [SNew(SHorizontalBox).IsEnabled_Lambda([this]{return !Session->Busy();})
                        +SHorizontalBox::Slot().FillWidth(1).Padding(0,0,24,0)[World]
                        +SHorizontalBox::Slot().FillWidth(1).Padding(24,0)[Algorithms]
                        +SHorizontalBox::Slot().FillWidth(1).Padding(24,0,0,0)[Events]]]
                +SVerticalBox::Slot().AutoHeight().Padding(0,14)[LabelDynamic([this]{return Session->Error.IsEmpty()?Session->Message:Session->Error;},12,Warning)]
                +SVerticalBox::Slot().AutoHeight()[SNew(SHorizontalBox)
                    +SHorizontalBox::Slot().FillWidth(1).VAlign(VAlign_Center)[Label(TEXT("Старт на паузе · наблюдение → план → физическое исполнение → подтверждение"),12,Muted)]
                    +SHorizontalBox::Slot().AutoWidth()[Button(TEXT("Подготовить и открыть мир  →"),[this]{Session->Prepare();},TAttribute<bool>::CreateLambda([this]{return Session->CanPrepare();}),true)]]];
    }
    TSharedRef<SWidget> BuildPresets()
    {
        return SNew(SVerticalBox)
            +SVerticalBox::Slot().AutoHeight()[SNew(SComboButton).ButtonStyle(&Styles().Normal).ContentPadding(FMargin(12,8)).ForegroundColor(Ink)
                .OnGetMenuContent_Lambda([this]()->TSharedRef<SWidget>{auto Menu=SNew(SVerticalBox);
                    if(Session->Presets.IsEmpty())Menu->AddSlot().AutoHeight().Padding(10)[Label(TEXT("Сохранённых пресетов пока нет"),12,Muted)];
                    for(const auto& Value:Session->Presets){const auto Preset=Value->AsObject();Menu->AddSlot().AutoHeight()[Button(Text(Preset,TEXT("title")),[this,Preset]{Session->LoadPreset(Text(Preset,TEXT("id")));FSlateApplication::Get().DismissAllMenus();})];}
                    return SNew(SBox).MaxDesiredHeight(400)[SNew(SScrollBox)+SScrollBox::Slot()[Menu]];})
                .ButtonContent()[Label(TEXT("Загрузить пресет"),12)]]
            +SVerticalBox::Slot().AutoHeight().Padding(0,8,0,0)[SNew(SHorizontalBox)
                +SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[SNew(SBox).WidthOverride(218)[SNew(SEditableTextBox).Text(Tx(PresetTitle)).Font(Font(12))
                    .OnTextChanged_Lambda([this](const FText& Value){PresetTitle=Value.ToString().Left(64);})]]
                +SHorizontalBox::Slot().AutoWidth().Padding(8,0,0,0)[Button(TEXT("Сохранить"),[this]{Session->SavePreset(PresetTitle);})]];
    }
    FString KeyStatus() const
    {
        if(!Session->Availability)return TEXT("Проверка локального ключа и бюджета…");
        return FString::Printf(TEXT("%s · общий LIVE-бюджет %d / %d"),Session->Availability->GetBoolField(TEXT("key_configured"))?TEXT("Ключ настроен"):TEXT("Ключ не настроен"),
            Session->Availability->GetIntegerField(TEXT("budget_used")),Session->Availability->GetIntegerField(TEXT("budget_limit")));
    }
    TSharedRef<SWidget> BuildHeader()
    {
        return SNew(SBorder).BorderImage(&Panel).Padding(FMargin(18,12))
            [SNew(SHorizontalBox)
                +SHorizontalBox::Slot().AutoWidth().Padding(0,0,30,0).VAlign(VAlign_Center)[Label(TEXT("META / RESCUE"),17,Accent)]
                +SHorizontalBox::Slot().FillWidth(1).VAlign(VAlign_Center)[LabelDynamic([this]{return Session->StageLabel();},16)]
                +SHorizontalBox::Slot().AutoWidth().Padding(18,0).VAlign(VAlign_Center)[SNew(SBox).WidthOverride(132)
                    [SNew(STextBlock).Text_Lambda([this]{return Tx(FString::Printf(TEXT("%.1f с"),Session->Mission.IsValid()&&Session->Mission->CoreRuntime?Session->Mission->CoreRuntime->Time():0));}).Font(Font(22)).ColorAndOpacity(Accent)]]
                +SHorizontalBox::Slot().AutoWidth().Padding(18,0).VAlign(VAlign_Center)[SNew(SBox).WidthOverride(230)
                    [LabelDynamic([this]{auto O=Session->Observation();if(!O)return FString(TEXT("Ожидание наблюдения"));auto M=O->GetObjectField(TEXT("metrics"));return FString::Printf(TEXT("Найдено %d  /  Передано %d"),M->GetIntegerField(TEXT("known_targets")),M->GetIntegerField(TEXT("confirmed_evacuations")));},13)]]
                +SHorizontalBox::Slot().AutoWidth()[Button(TEXT("Аналитика ↗"),[this]{Session->OpenAnalytics();})]];
    }
    TSharedRef<SWidget> BuildControls()
    {
        return SNew(SBorder).BorderImage(&Panel).Padding(10)
            [SNew(SHorizontalBox)
                +SHorizontalBox::Slot().AutoWidth()[Button(TEXT("▶ Продолжить"),[this]{Session->Run();},TAttribute<bool>::CreateLambda([this]{return Session->Stage==TEXT("paused");}),true)]
                +SHorizontalBox::Slot().AutoWidth().Padding(8,0)[Button(TEXT("Ⅱ Пауза"),[this]{Session->Pause();},TAttribute<bool>::CreateLambda([this]{return Session->Stage==TEXT("running");}))]
                +SHorizontalBox::Slot().AutoWidth()[Button(TEXT("+1 секунда"),[this]{Session->Step();},TAttribute<bool>::CreateLambda([this]{return Session->Stage==TEXT("paused");}))]
                +SHorizontalBox::Slot().AutoWidth().Padding(8,0)[Button(TEXT("■ Остановить"),[this]{Session->Stop();},TAttribute<bool>::CreateLambda([this]{return Session->CanOperate();}))]
                +SHorizontalBox::Slot().FillWidth(1).VAlign(VAlign_Center).Padding(16,0)[LabelDynamic([this]{return Session->Error.IsEmpty()?Session->Message:Session->Error;},11,Warning)]
                +SHorizontalBox::Slot().AutoWidth()[Button(TEXT("Повторить"),[this]{Session->Prepare();},TAttribute<bool>::CreateLambda([this]{return Session->Stage==TEXT("complete")||Session->Stage==TEXT("error");}))]
                +SHorizontalBox::Slot().AutoWidth().Padding(8,0,0,0)[Button(TEXT("Настройки"),[this]{Session->NewSetup();},TAttribute<bool>::CreateLambda([this]{return Session->Stage==TEXT("complete")||Session->Stage==TEXT("error");}))]];
    }
    TSharedRef<SWidget> BuildLayers()
    {
        auto Rows=SNew(SVerticalBox);
        Rows->AddSlot().AutoHeight().Padding(0,0,0,10)[Label(TEXT("Слои мира"),14,Accent)];
        for(const auto& Entry:TArray<TPair<bool UMRMissionSession::*,FString>>{
            {&UMRMissionSession::ObserverView,TEXT("Полный наблюдатель")},{&UMRMissionSession::ShowTrails,TEXT("Пройденные траектории")},
            {&UMRMissionSession::ShowRoutes,TEXT("Текущие маршруты")},{&UMRMissionSession::ShowNetwork,TEXT("Радиосеть")},
            {&UMRMissionSession::ShowHazards,TEXT("Опасности")},{&UMRMissionSession::ShowCoverage,TEXT("Обследование")},
            {&UMRMissionSession::ShowScenarios,TEXT("Коалиции и сценарии")},{&UMRMissionSession::InspectorOpen,TEXT("Инспектор агента")}})
            Rows->AddSlot().AutoHeight().Padding(0,5)[Toggle(Entry.Key,Entry.Value)];
        Rows->AddSlot().AutoHeight().Padding(0,12,0,0)[LabelDynamic([this]{return Session->ObserverView?
            TEXT("Физическая истина доступна наблюдателю. Контроллер получает только доставленные сведения."):
            TEXT("Схема команды: объявленные объёмы, доставленные позы и цели. Разрывы связи не заполняются.");},10,Muted)];
        Rows->AddSlot().AutoHeight().Padding(0,8,0,0)[Label(TEXT("Сплошной след — пройдено. Пунктир — текущая команда. До 2048 точек на агента."),10,Muted)];
        Rows->AddSlot().AutoHeight().Padding(0,12,0,0)[Label(TEXT("RMB · поворот\nКолесо · масштаб\nWASD · перемещение\nR · следить за агентом"),10,Muted)];
        return SNew(SBorder).BorderImage(&Panel).Padding(16)[Rows];
    }
    Object Selected() const
    {
        auto O=Session->Observation();if(!O)return nullptr;
        const auto& Agents=O->GetArrayField(TEXT("agents"));
        for(const auto& V:Agents)if(Text(V->AsObject(),TEXT("id"))==Session->SelectedAgent)return V->AsObject();
        return Agents.IsEmpty()?nullptr:Agents[0]->AsObject();
    }
    FString InspectorText() const
    {
        const auto A=Selected();if(!A)return TEXT("Ожидание доставленных показаний…");
        const auto P=A->GetObjectField(TEXT("physical")),C=A->GetObjectField(TEXT("communication"));
        const auto F=A->GetObjectField(TEXT("freshness"))->GetObjectField(TEXT("position"));
        double At=0;const bool Known=F->TryGetNumberField(TEXT("observed_at"),At);
        const double Now=Session->Mission.IsValid()&&Session->Mission->CoreRuntime?Session->Mission->CoreRuntime->Time():At;
        FString Out=FString::Printf(TEXT("%s  ·  %s\n\nСостояние: %s\nРоль: %s\nГруз: %s\n\nЗаряд: %.2f / %.2f Wh\nИзрасходовано: %.2f Wh\nПройдено: %.1f м\n\nСвязь: %s · качество %.0f%%\nПоказания: %s\nОстановка: %s\nКоманда: %s"),
            *Text(A,TEXT("id")),*Text(A,TEXT("kind")),*Text(P,TEXT("state")),Text(A,TEXT("role")).IsEmpty()?TEXT("не назначена"):*Text(A,TEXT("role")),
            Text(P,TEXT("cargo_target_id")).IsEmpty()?TEXT("пусто"):*Text(P,TEXT("cargo_target_id")),P->GetNumberField(TEXT("remaining_wh")),P->GetNumberField(TEXT("capacity_wh")),
            P->GetNumberField(TEXT("consumed_wh")),P->GetNumberField(TEXT("distance_m")),C->GetBoolField(TEXT("reachable"))?TEXT("доступна"):TEXT("нет доставки"),100*C->GetNumberField(TEXT("quality")),
            Known?*FString::Printf(TEXT("%.2f с назад"),FMath::Max(0.,Now-At)):TEXT("время неизвестно"),Text(P,TEXT("stop_reason")).IsEmpty()?TEXT("—"):*Text(P,TEXT("stop_reason")),*Text(P,TEXT("active_command_id")));
        return Out;
    }
    FString PlanText() const
    {
        auto O=Session->Observation();if(!O)return TEXT("План ещё не принят.");
        auto Plan=O->GetObjectField(TEXT("metaevolution"))->GetObjectField(TEXT("plan"));
        int32 Confirmed=0,Total=0;
        const auto Acks=Plan->GetObjectField(TEXT("agent_acknowledgements"));
        for(const auto& Pair:Acks->Values){++Total;double R=0;if(Pair.Value->AsObject()->TryGetNumberField(TEXT("plan_revision"),R)&&R==Plan->GetNumberField(TEXT("revision")))++Confirmed;}
        FString Proposed=TEXT("—");if(Session->Health&&Is(Session->Health,TEXT("last_decision"),EJson::Object))Proposed=Text(Session->Health->GetObjectField(TEXT("last_decision")),TEXT("operation"));
        return FString::Printf(TEXT("Предложено: %s\nПринята редакция: %d\nПодтверждено агентами: %d / %d"),*Proposed,Plan->GetIntegerField(TEXT("revision")),Confirmed,Total);
    }
    FString AIText() const
    {
        const FString Mode=Text(Group(TEXT("controller")),TEXT("ai_mode"));
        if(!Session->Health||!Is(Session->Health,TEXT("ai"),EJson::Object))return TEXT("AI ")+Mode+TEXT(" · ")+(Mode==TEXT("OFF")?TEXT("алгоритмическое управление"):TEXT("ожидание первого ответа"));
        const auto AI=Session->Health->GetObjectField(TEXT("ai"));
        const FString AIMode=Text(AI,TEXT("mode"));
        FString Out=TEXT("AI ")+AIMode+TEXT(" · ")+(AIMode==TEXT("MOCK")?TEXT("детерминированные ответы"):
            AI->GetBoolField(TEXT("api_confirmed"))?TEXT("API ответил"):TEXT("API ещё не подтверждён"));
        if(Is(AI,TEXT("pending"),EJson::Number))Out+=FString::Printf(TEXT("\nОжидается: %d"),AI->GetIntegerField(TEXT("pending")));
        if(Is(AI,TEXT("applied"),EJson::Object)){auto Applied=AI->GetObjectField(TEXT("applied"));Out+=FString::Printf(TEXT(" · применено G%d / L%d"),Applied->GetIntegerField(TEXT("global")),Applied->GetIntegerField(TEXT("local")));}
        if(Is(AI,TEXT("counters"),EJson::Object)){auto Counters=AI->GetObjectField(TEXT("counters"));Out+=FString::Printf(TEXT("\nРезерв: %d · отклонено: %d · timeout: %d"),Counters->GetIntegerField(TEXT("fallbacks")),Counters->GetIntegerField(TEXT("rejected")),Counters->GetIntegerField(TEXT("timeouts")));}
        return Out;
    }
    void FollowSelected()
    {
        const auto A=Selected();if(!A||!Session->Mission.IsValid())return;
        Session->SelectedAgent=Text(A,TEXT("id"));
        for(TActorIterator<AMRCameraPawn> It(Session->GetWorld());It;++It)It->FollowAgent(Session->SelectedAgent);
    }
    TSharedRef<SWidget> BuildInspector()
    {
        return SNew(SBorder).BorderImage(&Panel).Padding(18)[SNew(SScrollBox)+SScrollBox::Slot()[SNew(SVerticalBox)
            +SVerticalBox::Slot().AutoHeight()[Label(TEXT("Показания команды"),17,Accent)]
            +SVerticalBox::Slot().AutoHeight().Padding(0,14)[SNew(SComboButton).ButtonStyle(&Styles().Normal).ContentPadding(FMargin(10,8)).ForegroundColor(Ink)
                .OnGetMenuContent_Lambda([this]()->TSharedRef<SWidget>{auto Menu=SNew(SVerticalBox);auto O=Session->Observation();
                    if(O)for(const auto& V:O->GetArrayField(TEXT("agents"))){const FString Id=Text(V->AsObject(),TEXT("id"));Menu->AddSlot().AutoHeight()[Button(Id,[this,Id]{Session->SelectedAgent=Id;FSlateApplication::Get().DismissAllMenus();})];}
                    return SNew(SBox).MaxDesiredHeight(400)[SNew(SScrollBox)+SScrollBox::Slot()[Menu]];})
                .ButtonContent()[SNew(STextBlock).Text_Lambda([this]{auto A=Selected();return Tx(A?Text(A,TEXT("id")):TEXT("Выбрать агента"));}).Font(Font(13))
                    .ColorAndOpacity_Lambda([this]{auto A=Selected();return A?MRDisplayColor(Text(A,TEXT("id"))):Ink;})]]
            +SVerticalBox::Slot().AutoHeight()[LabelDynamic([this]{return InspectorText();},12)]
            +SVerticalBox::Slot().AutoHeight().Padding(0,14)[Button(TEXT("Следить за агентом"),[this]{FollowSelected();})]
            +SVerticalBox::Slot().AutoHeight().Padding(0,10)[LabelDynamic([this]{return PlanText();},11,Muted)]
            +SVerticalBox::Slot().AutoHeight().Padding(0,14)[LabelDynamic([this]{return AIText();},11,Accent)]
        ]];
    }
};
}

TSharedRef<SWidget> MRBuildMissionInterface(UMRMissionSession* Session)
{return SNew(SMRMissionInterface).Session(Session);}
