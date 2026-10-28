# tc-emulator

Interpreter ograniczonego podzbioru Structured Text napisany w Pythonie.
Uruchamia funkcje, bloki funkcyjne i programy PLC z GVL bez instalacji TwinCAT, również na Linuxie.
Przeznaczony do szybkich testów logiki w Pythonie/pytest.

**Wersja 0.17 obsługuje ograniczony podzbiór TwinCAT 3.** Poniżej opisujemy
obsługiwane konstrukcje; pozostałe są odrzucane. Przejście testu nie potwierdza
pełnej zgodności z runtime Beckhoff. Nie wykonuje binariów ani bibliotek TwinCAT.

## Instalacja

Wymagany Python 3.11 lub nowszy. Sam runtime nie ma zewnętrznych zależności.
Z katalogu projektu:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

Jeżeli używasz `uv`, zamiast dwóch pierwszych poleceń możesz wykonać:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

Na Windows użyj `.venv\Scripts\python.exe` zamiast `.venv/bin/python`.

## Funkcje

```python
from tc_emulator import Runtime

runtime = Runtime.from_source("""
FUNCTION F_Add : DINT
VAR_INPUT
    a, b : DINT;
END_VAR
F_Add := a + b;
END_FUNCTION
""")

assert runtime.call("F_Add", a=2, b=3).value == 5
```

`Runtime.from_files([...])` wczytuje zestaw plików `.st`, prostych `.TcPOU`, `.TcDUT`, `.TcGVL` i `.TcIO`.
Wszystkie jednostki są walidowane razem, niezależnie od kolejności plików.
Funkcja przy każdym wywołaniu otrzymuje świeże zmienne lokalne. Dodatkowe
`VAR_OUTPUT` są dostępne w niemodyfikowalnym `result.outputs`.

## Bloki funkcyjne

Uruchomienie z katalogu projektu, z dołączonym plikiem przykładowym:

```python
from tc_emulator import Runtime

runtime = Runtime.from_files(["examples/FB_Counter.TcPOU"])
counter = runtime.instantiate("FB_Counter")
counter.set_input("enable", True)  # Ustawienie wejścia nie wykonuje kodu.
counter.call()
counter.call()
assert counter.output("count") == 2

other = runtime.instantiate("FB_Counter")
assert other.output("count") == 0
```

Wywołania są jawne, bez automatycznego skanowania PLC. FB zachowuje `VAR`, wejścia,
wyjścia i zagnieżdżone instancje. Pominięty `VAR_INPUT` zachowuje poprzednią wartość;
`VAR_TEMP` jest inicjalizowane przy każdym wywołaniu. `inspect()` zwraca odłączoną
kopię stanu do diagnostyki, z nazwami zapisanymi wielkimi literami. Modyfikowanie
tej kopii nie zmienia instancji.

## Przekazywanie przez referencję

```python
from tc_emulator import Runtime

runtime = Runtime.from_files(["examples/functions.st"])
value = runtime.cell("DINT", 10)
runtime.call("F_Increment", value=value)
assert value.value == 11
```

`VAR_IN_OUT` wymaga komórki zgodnego typu z tego samego Runtime; aliasy typów
nie zmieniają zgodności.
Zmiany są natychmiast widoczne przez aliasy. Wszystkie parametry IN_OUT trzeba
przekazać przy każdym wywołaniu, także dla FB. Funkcje wymagają również wszystkich
VAR_INPUT (wyjątek: wejścia referencyjne z jawnym domyślnym 0 w v0.14).
W API Pythona argumenty ST przekazuje się nazwami; w samym ST funkcje
obsługują wywołania pozycyjne lub nazwane. Nie można mieszać obu form.

## Obsługiwany zakres

- FUNCTION, FUNCTION_BLOCK, PROGRAM; VAR, VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT i VAR_TEMP w FB/PROGRAM.
- GVL, VAR_GLOBAL/VAR_GLOBAL CONSTANT, qualified_only; jawne skany i cykle z wirtualnym czasem.
  PROGRAM nie obsługuje VAR_IN_OUT.
- BOOL, INT, UINT, DINT, UDINT, BYTE, WORD, DWORD, REAL, LREAL, TIME oraz STRING(n) Latin-1.
- Literały dziesiętne, 2#/8#/16#, typowane literały liczbowe, boolowskie i czasowe.
- Wbudowane timery TON, TOF, TP ze wspólnym wirtualnym zegarem Runtime.
- R_TRIG, F_TRIG, SR, RS, CTU, CTD, CTUD; funkcje standardowe i jawne konwersje typów.
- Lokalne VAR CONSTANT, wyrażenia stałe, nazwane granice tablic i etykiety CASE.
- TYPE: aliasy, STRUCT i enumy, także strict/qualified_only; inicjalizacja i typy zagnieżdżone.
- Stałe tablice, również wielowymiarowe i tablice struktur/enumów; inicjalizatory i powtórzenia.
- Tablice instancji FB, indeksowane wywołania i metody; ARRAY[*] w VAR_IN_OUT typów wartościowych.
- LOWER_BOUND/UPPER_BOUND dla tablic stałych i otwartych parametrów.
- Arytmetyka `+ - * / MOD`, porównania, boolowskie i bitowe AND/OR/XOR/NOT.
- Referencje do danych `REFERENCE TO`, wiązanie `REF=`, `__ISVALIDREF` i BOOL AND_THEN/OR_ELSE.
- SHL/SHR/ROL/ROR oraz odczyt/zapis bitów, np. `status.0`, `command.cEnable`.
- Funkcje tekstowe LEN/LEFT/RIGHT/MID/CONCAT/FIND/INSERT/DELETE/REPLACE i konwersje tekstu.
- IF/ELSIF/ELSE, CASE, FOR/TO/BY, WHILE, RETURN, EXIT.
- Funkcje w wyrażeniach, zagnieżdżone FB, dostęp do ich wejść/wyjść, wiązania `=>`.
- Akcje ST w FB i PROGRAM: ACTION, wywołania lokalne, przez instancję i z Pythona.
- Metody FB: METHOD, PUBLIC/PROTECTED/PRIVATE, parametry i wyniki, wywołania ze ST i Pythona.
- Właściwości FB PROPERTY GET/SET, THIS^ oraz VAR_INST w metodach FB.
- INTERFACE/IMPLEMENTS, zmienne interfejsowe i dynamiczne wywołania metod/właściwości.
- Pojedyncze dziedziczenie FB przez EXTENDS, nadpisania metod/właściwości/akcji i SUPER^.
- Inicjalizacja FB przez FB_init, parametry deklaracji, przypisania wejść/właściwości
  po FB_init i hooki call_after_init, także dla dziedziczenia i tablic FB.
- Nazwy bez rozróżniania wielkości liter; komentarze `//` i zagnieżdżone `(* ... *)`.
- Import deklaracji i implementacji ST z `.TcPOU`, w tym metod, właściwości FB oraz akcji FB/PROGRAM.
- Import pojedynczej deklaracji typu z prostego `.TcDUT` i listy globalnej z `.TcGVL`.
- Import kontraktów metod i właściwości interfejsu z `.TcIO`.

Poza zakresem pozostają LTIME, DATE/TOD/DT, WSTRING i tekst UTF-8,
RETAIN/PERSISTENT, VAR_EXTERNAL, metody i właściwości PROGRAM,
dziedziczenie interfejsów, atrybuty poza GVL qualified_only, enumów strict/qualified_only i FB/metod call_after_init,
FB_exit/FB_reinit, online change, biblioteki zewnętrzne,
ogólne wskaźniki, referencje do FB/interfejsów i referencje zagnieżdżone.
Obsługiwane mechanizmy aliasowania to VAR_IN_OUT, zmienne interfejsowe,
REFERENCE TO danych oraz ograniczony dostęp THIS^/SUPER^. LWORD/LINT/ULINT, pola typu BIT oraz częściowy dostęp `.%B`/`.%W`
nie są obsługiwane.
Nieznane konstrukcje, także w niewywoływanym kodzie, powodują błąd podczas wczytywania.

## REAL/LREAL i tablice (v0.2)

Z katalogu projektu możesz uruchomić dołączone przykłady:

```python
from tc_emulator import Runtime

runtime = Runtime.from_files(["examples/real_arrays.st", "examples/FB_Samples.TcPOU"])
assert runtime.call("F_Mean", samples=[1.0, 2.0, 3.0, 4.0]).value == 2.5
assert runtime.call("F_Trace", matrix=[[1.5, 2.0], [3.0, 4.5]]).value == 6.0

values = runtime.cell("ARRAY[-1..1] OF REAL", [1.0, 2.0, 3.0])
runtime.call("F_Scale", values=values, factor=0.5)
assert values.value == (0.5, 1.0, 1.5)
values.element(-1).value = 10.0  # Pierwszy element według granic ST.
```

W ST można deklarować i modyfikować tablice na przykład tak:

```iecst
VAR
    matrix : ARRAY[-1..0, 3..4] OF REAL := [10.0, 20.0, 30.0];
    samples : ARRAY[1..4] OF LREAL := [3(1.5), 2.0];
END_VAR
matrix[0, 4] := samples[1];
```

Granice są włączne, mogą być ujemne i nie muszą zaczynać się od zera.
Ostatni wymiar zmienia się najszybciej: inicjalizacja `matrix` daje
`((10.0, 20.0), (30.0, 0.0))`. Pominięte elementy inicjalizatora otrzymują wartość
domyślną typu elementu: np. zero/FALSE albo zadeklarowane wartości pól struktury.
W Pythonie podawaj zagnieżdżone listy lub tuple o dokładnym kształcie.
Wartości tablic w wynikach `.value`, `output()` i `inspect()` są odłączonymi,
niemodyfikowalnymi tuple.

Tablice są obsługiwane jako zmienne lokalne, VAR_TEMP, parametry, wyjścia i wyniki
funkcji. Zwykłe przypisanie oraz VAR_INPUT/VAR_OUTPUT kopiują wartości;
VAR_IN_OUT przekazuje wspólną pamięć. `cell.element(*indices)` udostępnia również
pojedynczy element do przekazania przez referencję. Przypisanie całej tablicy
zachowuje istniejące aliasy elementów. Parametry o stałych granicach wymagają
identycznego typu i granic tablic; otwarte parametry opisano w sekcji v0.10.
Nieprawidłowy indeks zgłasza błąd — nie stosujemy ujemnego indeksowania Pythona.

Tablica może mieć 1–8 wymiarów i najwyżej 1 000 000 elementów. Elementami mogą być
skalary, struktury, enumy i aliasy typów, również aliasy tablic. Dla aliasów tablic
indeksowanie jest zagnieżdżone, np. `matrix[1][2]`. Bezpośrednia składnia
`ARRAY OF ARRAY` oraz listy tablicowe użyte jako ogólne wyrażenia
pozostają poza zakresem. `[2(1.0)]` jest inicjalizatorem
w deklaracji; do kopiowania podczas wykonania używaj `destination := source`.

REAL zapisuje IEEE754 binary32, LREAL binary64. Literały bez prefiksu (`1.5`, `2e-3`)
mają w tym profilu typ LREAL; `REAL#1.5` i `LREAL#1.5` określają go jawnie.
API przyjmuje int/float, lecz odrzuca bool, NaN i Infinity. Przykładowo REAL zapisuje
16777217 jako 16777216.0, podczas gdy LREAL zachowuje 16777217.0.
Konwersja liczb całkowitych i literałów `REAL#...` zaokrągla dokładną wartość
bezpośrednio do binary32, do najbliższej liczby, a w połowie — do parzystej mantysy.

## TIME i timery z wirtualnym czasem (v0.3)

Zegar każdego Runtime zaczyna od zera. `advance_time(milliseconds=...)` przesuwa
go o podaną liczbę milisekund, bez czekania. Następnie jawnie wywołujesz FB:

```python
from tc_emulator import Runtime

runtime = Runtime.from_files(["examples/FB_Delayed.TcPOU"])
block = runtime.instantiate("FB_Delayed")
block.call(enable=True)  # TON zaczyna odliczać zadane w ST T#1s.
runtime.advance_time(milliseconds=999)
block.call()
assert block.output("ready") is False
assert block.output("elapsed") == 999
runtime.advance_time(milliseconds=1)
block.call()
assert block.output("ready") is True
assert runtime.now_ms == 1000
```

Samo przesunięcie zegara ani odczyt wyjścia nie wykonują programu. `Q` i `ET`
zmieniają się podczas wywołania timera. Wszystkie timery zagnieżdżone w jednym
wywołaniu widzą ten sam czas. Kolejne wywołania bez `advance_time` nie przyspieszają
odliczania. Zegar nie zawija się po 32 bitach i przyjmuje dowolny nieujemny `int`;
odrzuca `bool`, `float` i wartości ujemne. `now_ms` służy tylko do odczytu.

Timery mają wejścia `IN:BOOL`, `PT:TIME` i wyjścia `Q:BOOL`, `ET:TIME`.
Są dostępne bez deklarowania biblioteki. Można ich użyć w zwykłym ST:

```iecst
FUNCTION_BLOCK FB_Delay
VAR_INPUT enable : BOOL; END_VAR
VAR_OUTPUT ready : BOOL; elapsed : TIME; END_VAR
VAR timer : TON; END_VAR
timer(IN := enable, PT := T#1s, Q => ready, ET => elapsed);
END_FUNCTION_BLOCK
```

| Timer | Zachowanie |
|---|---|
| TON | Po włączeniu IN czeka PT; następnie Q=TRUE. IN=FALSE zeruje Q i ET. |
| TOF | IN=TRUE natychmiast ustawia Q. Po wyłączeniu IN utrzymuje Q przez PT. |
| TP | Zbocze narastające IN uruchamia impuls Q o długości PT, niezależny od późniejszych zmian IN. |

`ET` rośnie do czasu zapamiętanego przy starcie. Każda instancja ma niezależny stan.
Pominięte wejścia zachowują wartości, jak w pozostałych FB. Timer lokalny funkcji
lub zadeklarowany w `VAR_TEMP` zaczyna od nowa przy każdym wywołaniu.

Jawne zasady tego profilu:

- `PT` jest zapamiętywane przy starcie odliczania. Zmiana wejścia `PT` w trakcie
  nie zmienia bieżącego odliczania; następny start użyje nowej wartości.
- Dla `PT=0` TON i TOF od razu odwzorowują IN; TP nie emituje widocznego impulsu.
- TOF z początkowym IN=FALSE pozostaje wyłączony. Zbocze narastające przerywa
  trwające opóźnienie wyłączenia i zeruje ET.
- TP ignoruje zbocza w trakcie impulsu. Ponowne uruchomienie wymaga wywołania
  z IN=FALSE przy zakończeniu lub po zakończeniu, a następnie z IN=TRUE.
  Jeśli IN jest FALSE przy zakończeniu, ET zeruje się w tym samym wywołaniu;
  przy TRUE pozostaje równe zapamiętanemu PT. Impuls nie odnawia się przy stale TRUE.

Podstawowe przebiegi odpowiadają opisom Beckhoff:
[TON](https://infosys.beckhoff.com/content/1033/tcplclib_tc2_standard/74406539.html),
[TOF](https://infosys.beckhoff.com/content/1033/tcplclib_tc2_standard/74405003.html),
[TP](https://infosys.beckhoff.com/content/1033/tcplclib_tc2_standard/74408075.html).
Powyższe szczegóły zmian PT i kolejności próbkowania są jawnymi regułami emulatora;
nie wykonano porównania z fizycznym runtime TwinCAT.

Możesz również testować sam timer bez pliku ST:

```python
runtime = Runtime.from_source("")
timer = runtime.instantiate("TP")
timer.call(IN=True, PT=1000)  # Python: PT i ET w całkowitych milisekundach.
runtime.advance_time(1000)
timer.call()
assert timer.output("Q") is False
```

`TIME` przechowuje 0..4294967295 ms, zgodnie z
[32-bitowym typem TIME](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/12189021579.html).
W ST używaj `T#250ms`, `TIME#1.5s`, `T#1h_2m_3s`; jednostki to `d,h,m,s,ms`
w kolejności malejącej. Ułamek może wystąpić tylko w ostatniej jednostce i musi
dawać całkowite milisekundy. Najwyższa podana jednostka może przekroczyć zwykły
zakres, np. `T#100s12ms`; niższe muszą się w nim mieścić, więc `T#5m68s` jest błędem.

TIME działa w parametrach, wynikach funkcji, tablicach i `VAR_IN_OUT`.
Dozwolone są dodawanie/odejmowanie dwóch TIME oraz ich porównania.
Przepełnienie lub wynik ujemny daje błąd; nie ma niejawnych konwersji z liczb ST.
Mnożenie, dzielenie, MOD, ujemne czasy, LTIME i rozdzielczość poniżej 1 ms pozostają
poza zakresem. W API Pythona TIME przyjmuje wyłącznie `int` w podanym zakresie.

Pliki `examples/timers.st`, `examples/FB_Delayed.TcPOU` i `examples/test_timers.py`
pokazują wszystkie trzy timery oraz wykonywanie funkcji zwracającej TIME:

```bash
.venv/bin/python -m pytest examples/test_timers.py -q
```

## TYPE, STRUCT i enumy (v0.4)

Typy można deklarować w jednym lub kilku blokach TYPE. Mogą odwoływać się do
typów zadeklarowanych później, także w innym wczytywanym pliku:

```iecst
TYPE
    T_Speed : REAL := 1.5;
    E_State : (Idle := 0, Waiting := 10, Running := 20) INT := Idle;
    ST_Config : STRUCT
        speed : T_Speed;
        delay : TIME := T#100ms;
        enabled : BOOL := TRUE;
    END_STRUCT;
    T_Recipe : ARRAY[-1..1] OF ST_Config;
END_TYPE
```

Enum zapisujemy jako listę członków w nawiasach, bez osobnego słowa `ENUM`.
W kodzie używaj kwalifikowanych nazw, np. `E_State.Running`; działają również
jako etykiety CASE. Od v0.16 enum bez `qualified_only` dopuszcza też skróconą
nazwę członka, jeśli jest jednoznaczna i nie przesłania jej zmienna lub stała.
Wartość domyślna deklarowanego enumu może używać skrótu także z `qualified_only`.

Pola, indeksy i inicjalizatory można zagnieżdżać:

```iecst
FUNCTION F_Recipe : T_Recipe
VAR
    configs : T_Recipe := [(speed := 2, delay := T#50ms), (speed := 4)];
END_VAR
configs[-1].speed := configs[-1].speed + 1;
F_Recipe := configs;
END_FUNCTION
```

Pominięte pola i elementy korzystają z wartości domyślnych zadeklarowanego typu.
Tutaj trzecia konfiguracja ma `speed=1.5`, `delay=T#100ms`, `enabled=TRUE`.
Inicjalizatory `(field := value)` i `[...]` są dostępne w deklaracjach;
podczas wykonania można przypisywać pola albo kopiować całe wartości przez `:=`.

Z katalogu projektu uruchom kompletny przykład:

```python
from tc_emulator import Runtime

runtime = Runtime.from_files(["examples/user_types.st", "examples/ST_Config.TcDUT"])
config = runtime.cell("ST_Config", {"speed": 2.0})
speed = config.field("speed")

# VAR_INPUT kopiuje strukturę; wynik jest odłączoną wartością.
changed = runtime.call("F_Accelerated", config=config.value).value
assert changed["speed"] == 3.0
assert config.value["speed"] == 2.0
assert changed["delay"] == 100  # TIME w milisekundach.

# VAR_IN_OUT modyfikuje przekazaną komórkę.
runtime.call("F_SetSpeed", config=config, speed=7.5)
assert speed.value == 7.5
config.value = {"speed": 4.0}
assert speed.value == 4.0  # Referencja przetrwała zastąpienie całej struktury.

recipe = runtime.cell("T_Recipe", runtime.call("F_Recipe").value)
recipe.element(-1).field("speed").value = 8.0

machine = runtime.instantiate("FB_Machine")
machine.call(start=True, config={"speed": 6.0, "delay": 1000})
assert machine.output("state").name == "WAITING"
runtime.advance_time(1000)
machine.call()
assert machine.output("state").name == "RUNNING"
assert machine.output("activeSpeed") == 6.0
```

Na granicy API struktura przyjmuje słownik/mapping. Nazwy pól ignorują wielkość
liter; nieznane lub powtórzone pola są błędem. Brakujące pola przyjmują wartości
domyślne. Tablice w takim słowniku nadal muszą mieć dokładny kształt.
Wynik to niemodyfikowalny `StructValue`: odczyt `value["speed"]`, nazwa typu
w `.type_name`, iteracja po nazwach pól wielkimi literami. Zagnieżdżone tablice
są tuple, struktury — kolejnymi `StructValue`. Modyfikuj pamięć przez `Cell.value`,
`.field(name)` i `.element(*indices)`; zwykłe wyniki i `inspect()` są odłączone.

Enum w Pythonie przyjmuje napis `"Running"`, `"E_State.Running"` lub pasujący
`EnumValue` z wcześniejszego wyniku. Zwracany `EnumValue` udostępnia `.type_name`,
`.name` (wielkimi literami) i `.value` (liczbę). Surowe liczby i bool są odrzucane.

Jawne zasady tego profilu:

- Alias zachowuje zgodność z typem bazowym. Struktury i enumy mają tożsamość
  nazwanego typu: identyczny układ pól dwóch różnych struktur nie daje zgodności.
- Każda instancja otrzymuje własne wartości. VAR_INPUT, VAR_OUTPUT, wyniki funkcji
  i przypisania kopiują struktury; VAR_IN_OUT zachowuje wspólną pamięć.
- Enum domyślnie używa INT; można wybrać INT, UINT, DINT lub UDINT. Nienumerowany
  pierwszy członek ma wartość 0, następne zwiększają poprzednią o 1. Nazwy i wartości
  muszą być unikalne i mieścić się w typie bazowym. Bez jawnego domyślnego członka
  wybierany jest członek o wartości 0, a gdy go brak — pierwszy.
- Enumy można przypisywać i porównywać tylko w obrębie tego samego typu;
  arytmetyka i niejawne konwersje enum–liczba są odrzucane. Wyjątkiem od v0.16
  jest opisana niżej kontrolowana konwersja stałej całkowitej do enumu `strict`.
- Typ złożony może zawierać najwyżej 1 000 000 wartości skalarnych łącznie,
  a ścieżka odwołań do nazwanych typów najwyżej 64 poziomy. Cykle typów i puste
  struktury są odrzucane przed tworzeniem wartości domyślnych.
- Poza zakresem pozostają STRUCT EXTENDS, UNION, podzakresy, inne atrybuty enumów,
  przestrzenie nazw oraz pola/aliasy typu FB. Domyślne wartości struktury deklaruj
  przy polach lub przez inicjalizator aliasu; inicjalizacja po END_STRUCT nie jest obsługiwana.

Importer `.TcDUT` obsługuje pojedynczy `DUT` z sekcją `Declaration` i jednym typem,
którego nazwa zgadza się z atrybutem `Name`. To ograniczony format importu,
nie obsługa całego projektu TwinCAT.

Przykłady i ich testy znajdują się w `examples/user_types.st`,
`examples/ST_Config.TcDUT` oraz `examples/test_user_types.py`:

```bash
.venv/bin/python -m pytest examples/test_user_types.py -q
```

## Standardowe bloki, funkcje i stałe (v0.5)

Nowe bloki są dostępne w ST oraz przez `runtime.instantiate(...)`, bez bibliotek
zewnętrznych. Każda instancja zachowuje własny stan; pominięte wejścia zachowują
wartości. Wyjścia zmieniają się wyłącznie przy wywołaniu.

| Blok | Wejścia → wyjścia | Działanie |
|---|---|---|
| R_TRIG / F_TRIG | CLK → Q | Jedno wywołanie z Q=TRUE po zboczu narastającym / opadającym. |
| SR | SET1, RESET → Q1 | Podtrzymanie stanu; SET1 ma pierwszeństwo. |
| RS | SET, RESET1 → Q1 | Podtrzymanie stanu; RESET1 ma pierwszeństwo. |
| CTU | CU, RESET, PV → Q, CV | Zliczanie zboczy narastających CU; Q wskazuje CV≥PV. |
| CTD | CD, LOAD, PV → Q, CV | LOAD ustawia CV=PV, zbocza CD zmniejszają CV; Q wskazuje CV=0. |
| CTUD | CU, CD, RESET, LOAD, PV → QU, QD, CV | Liczenie w obu kierunkach; QU oznacza CV≥PV, QD oznacza CV=0. |

PV i CV mają typ WORD, czyli w tym profilu sprawdzaną liczbę całkowitą 0..65535.
WORD pozostaje odrębny od UINT przy wiązaniu VAR_IN_OUT i wyjść `=>`.
Liczniki zatrzymują się na 0/65535, nie na PV. W CTUD RESET ma pierwszeństwo
przed LOAD, a LOAD przed liczeniem; jednoczesne zbocza CU/CD znoszą się.
Pamięć zboczy aktualizuje się także podczas RESET/LOAD. R_TRIG może wykryć zbocze
przy pierwszym wywołaniu z TRUE; F_TRIG wymaga wcześniej odczytanego TRUE.
SR/RS reagują na poziomy wejść. Wyjścia przed pierwszym wywołaniem mają zero/FALSE.
To jawne reguły graniczne emulatora; interfejsy i podstawowe działanie opisuje
[Tc2_Standard](https://download.beckhoff.com/download/document/automation/twincat3/TwinCAT_3_PLC_Lib_Tc2_Standard_EN.pdf).

```python
from tc_emulator import Runtime

runtime = Runtime.from_source("")
counter = runtime.instantiate("CTU")
counter.call(CU=True, PV=2)
assert counter.output("CV") == 1
counter.call()  # Stale TRUE nie jest kolejnym zboczem.
assert counter.output("CV") == 1
counter.call(CU=False)
counter.call(CU=True)
assert counter.output("Q") is True
```

W wyrażeniach ST można wywoływać:

- `ABS(x)`, `MIN(a,b,...)`, `MAX(a,b,...)`, `LIMIT(minimum,x,maximum)`.
- `SEL(condition,a,b)`: FALSE wybiera a, TRUE wybiera b.
- `MUX(index,a,b,...)`: indeks 0 wybiera a; indeks ponad zakres wybiera ostatnią
  wartość, a ujemny powoduje błąd.
- Konwersje `X_TO_Y(value)` i `TO_Y(value)` dla BOOL, INT, UINT, DINT, UDINT,
  WORD, REAL, LREAL i TIME (od v0.6 także BYTE/DWORD), np. `REAL_TO_INT(speed)`
  i `TIME_TO_UDINT(delay)`.

Argumenty mogą być pozycyjne albo nazwane. ABS i konwersje przyjmują `IN`,
MIN/MAX — `IN0`, `IN1`, …, LIMIT — `MIN`, `IN`, `MAX` (również `MN`/`MX`),
SEL — `G`, `IN0`, `IN1`, MUX — `K`, `IN0`, … . Nie można mieszać obu form.
MIN/MAX wymagają co najmniej dwóch wartości; MUX co najmniej jednej alternatywy.
Są to operatory ST; z Pythona wywołuj funkcję ST, która ich używa.

SEL/MUX obliczają tylko wybraną gałąź, ale sprawdzanie typów obejmuje wszystkie
gałęzie. Dzięki temu poniższy kod nie dzieli przez zero:

```iecst
result := SEL(divisor <> 0.0, 0.0, numerator / divisor);
```

ABS działa na liczbach. MIN/MAX/LIMIT obsługują liczby oraz wartości jednakowego
typu TIME, BOOL lub enum. SEL/MUX dodatkowo obsługują zgodne tablice i struktury.
Aliasy są przezroczyste. Argumenty liczbowe wspólnie wybierają typ według reguł
arytmetyki; przy identycznych typach konkretnych wynik zachowuje ten typ,
np. ABS dla INT odrzuca -32768, ponieważ wynik nie mieści się w INT.
LIMIT odpowiada `MIN(MAX(x,minimum),maximum)`, także dla odwróconych granic.

Konwersje nie zawijają wartości i sprawdzają zakres typu docelowego. Float na
typ całkowity lub TIME zaokrąglamy do najbliższej liczby, a połowy do parzystej:
2.5→2, 3.5→4, -3.5→-4. Nazwany typ źródłowy jest sprawdzany przed konwersją
docelową; źródłowy REAL najpierw zaokrągla do binary32. Numeryczny typ źródłowy
akceptuje dane liczbowe, BOOL wymaga BOOL, a TIME wymaga TIME lub nietypowanego
literału całkowitego. `TO_Y` korzysta z typu argumentu. BOOL na liczbę daje 0/1,
konwersja na BOOL sprawdza różność od zera; TIME reprezentuje milisekundy.
Enumy i dane złożone nie podlegają tym konwersjom. NaN/Infinity są błędami.
Reguła zaokrąglania jest deterministycznym profilem emulatora; Beckhoff opisuje
zależności od platformy dla części przypadków granicznych
[konwersji](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529090443.html).

Stałe deklaruj lokalnie w funkcji lub FB:

```iecst
VAR CONSTANT
    cCount : INT := 3;
    cScale : INT := cCount * 2;
END_VAR
VAR
    values : ARRAY[1..cCount] OF INT := [cScale, cScale + 2, cScale + 4];
END_VAR
```

Inicjalizator stałej jest obowiązkowy. Obsługiwane są skalarne i złożone typy
wartościowe, odwołania do innych lokalnych stałych (również późniejszych),
członków enumów oraz operatory jedno- i dwuargumentowe. Nazwane stałe działają
w inicjalizatorach, granicach tablic oraz etykietach CASE. Zależności cykliczne,
zmienne modyfikowalne i wywołania funkcji w wyrażeniach stałych są odrzucane.
Stała nie może być celem przypisania, sterować FOR ani zostać przekazana jako
VAR_IN_OUT lub cel `=>`; dotyczy to również jej pól i elementów tablicy.
Przekazanie przez VAR_INPUT tworzy zwykłą modyfikowalną kopię.

W v0.5 dodano lokalne `VAR CONSTANT`; v0.8 rozszerza je o `VAR_GLOBAL CONSTANT`.
Nadal nie obsługujemy stałych wejściowych i instancji
FB jako stałych. Typy globalne nie widzą stałych lokalnych POU.
Przykład `examples/standard.st` łączy licznik partii, przerzutnik, TON, konfigurację
strukturalną i skalowanie wartości; `examples/test_standard_usage.py` uruchamia go
bez oczekiwania na rzeczywisty czas:

```bash
.venv/bin/python -m pytest examples/test_standard_usage.py -q
```

## Typy i operacje bitowe (v0.6)

BYTE ma zakres 0..255 (8 bitów), WORD 0..65535 (16 bitów), a DWORD
0..4294967295 (32 bity). Typy działają w strukturach, tablicach, stałych,
parametrach i konwersjach. Zapis wartości spoza zakresu jest błędem;
zwykła arytmetyka i konwersje nadal nie zawijają liczb.

Literały obsługują podstawy 2, 8 i 16 oraz typowanie:

```iecst
VAR CONSTANT
    cFlags : BYTE := 2#1000_0001;
    cMask : WORD := WORD#16#FF00;
    cAck : WORD := WORD#8#100000;
    cFull : DWORD := DWORD#16#FFFF_FFFF;
    cOffset : INT := INT#-1;
END_VAR
```

Podkreślenia można umieszczać tylko między cyframi. Prefiksy i cyfry A–F nie
rozróżniają wielkości liter. Typowany literał zachowuje wskazany typ i musi
mieścić się w jego zakresie; `INT#16#FFFF` jest błędem, a nie zapisem -1.
Nietypowany literał 2#/8#/16# wybiera najmniejszy BYTE/WORD/DWORD mieszczący
wartość; większe wartości są odrzucane. Nietypowany literał dziesiętny zachowuje
dotychczasową kategorię INTEGER. Literały całkowite działają również w granicach
tablic, etykietach CASE, wartościach enumów i licznikach powtórzeń inicjalizatora.

`AND`, `OR`, `XOR` i `NOT` obsługują zarówno BOOL, jak i BYTE/WORD/DWORD.
Nie można mieszać BOOL z liczbami. Dla różnych typów bitowych wynik ma szerokość
najszerszego argumentu. Nietypowany INTEGER przyjmuje szerokość drugiego
argumentu bitowego, a bez niego — DWORD. Wartość każdego argumentu musi mieścić
się w wybranym typie. Zmienne INT/UINT/DINT/UDINT wymagają jawnej konwersji
przed użyciem operatora bitowego. Przykładowo:

```iecst
inverted := NOT BYTE#0;                  // BYTE, 255
masked := WORD#16#ABCD AND WORD#16#00FF; // WORD, 205
combined := BYTE#16#01 OR WORD#16#8000;  // WORD, 32769
```

SHL/SHR przesuwają bity, a ROL/ROR obracają je w obrębie szerokości argumentu.
Argumenty to `IN` i `N`; można używać formy pozycyjnej lub nazwanej:

```iecst
shifted := SHL(BYTE#1, 7);              // BYTE, 128
cleared := SHL(BYTE#1, 8);              // BYTE, 0
rotated := ROL(BYTE#16#80, 9);          // BYTE, 1
highByte := WORD_TO_BYTE(SHR(IN := WORD#16#ABCD, N := 8)); // BYTE, 171
```

Wybrany profil: SHL/SHR dla `N >= szerokość` zwracają zero; ROL/ROR używają
`N modulo szerokość`. Ujemne N daje błąd, BOOL nie jest licznikiem przesunięcia.
Pierwszy argument musi być BYTE/WORD/DWORD lub nietypowanym INTEGER, dla którego
przyjmujemy DWORD. Dlatego `SHL(1, 16)` daje 65536, a `SHL(16#1, 16)` daje 0,
ponieważ literał `16#1` ma w tym profilu typ BYTE. Jawne prefiksy typów pozwalają
uniknąć tej różnicy. Szerokość wyniku zależy od argumentów, nie od zmiennej celu.
Beckhoff opisuje zależność niektórych przesunięć od platformy;
[reguła zerowania dla dużego N](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528939915.html)
jest świadomym wyborem emulatora.

Odczyt i zapis pojedynczego bitu używają indeksu od zera, podanego jako literał
lub lokalna stała całkowita:

```iecst
ready := status.0;
command.cEnableBit := TRUE;
config.words[1].7 := FALSE;
```

Obsługiwane są BYTE/WORD/DWORD oraz INT/UINT/DINT/UDINT. Indeks musi być stały
i mieścić się w szerokości typu; bit jest wartością BOOL. Dla INT/DINT zapis
najwyższego bitu zmienia znak zgodnie z uzupełnieniem do dwóch. Pozostałe bity
pozostają bez zmian. Bit stałej można czytać, lecz nie modyfikować. Dostęp bitowy
działa także dla publicznych wejść/wyjść FB oraz pól struktur i elementów tablic.

Widok bitu można obsługiwać również z Pythona:

```python
from tc_emulator import Runtime

runtime = Runtime.from_source("")
word = runtime.cell("WORD", 0xAA00)
enabled = word.bit(7)
enabled.value = True
assert word.value == 0xAA80
word.value = 0x5500
assert enabled.value is False
enabled.value = True
assert word.value == 0x5580
```

Widok zachowuje powiązanie również po zastąpieniu całej struktury lub tablicy
zawierającej słowo. Nie można przekazać bitu jako VAR_IN_OUT — ani w ST, ani
przez `Cell.bit()` w Pythonie. Przekaż całe słowo albo kopię BOOL przez VAR_INPUT;
cel wyjściowy `Q => word.0` jest dozwolony. W Pythonie wejście BOOL otrzymuje
`enabled.value`, nie sam widok.

Bitowe operatory infiksowe i odczyty stałych bitów działają w wyrażeniach stałych.
Wywołania funkcji, również SHL/SHR/ROL/ROR, pozostają poza inicjalizatorami stałymi.
`examples/bits.st` pokazuje dekodowanie statusu urządzenia, zmianę słowa sterującego,
pakowanie dwóch WORD w DWORD i rotację maski. Uruchom przykłady poleceniem:

```bash
.venv/bin/python -m pytest examples/test_bits_usage.py -q
```

## STRING i funkcje tekstowe (v0.7)

`STRING` oznacza `STRING(80)`. Obsługiwane są również zapisy `STRING(n)` i
`STRING[n]`, gdzie pojemność wynosi 1–1 000 000 bajtów. W ST może ją określać
całkowite wyrażenie stałe, również lokalne `VAR CONSTANT`. Tekst działa w aliasach,
strukturach, tablicach, parametrach, wynikach funkcji oraz stanie FB.

Profil używa **Latin-1**: jeden znak to jeden bajt. API Pythona przyjmuje `str`;
znaki spoza Latin-1 (np. euro, polskie `ą` lub emoji) są odrzucane, również gdy
znajdują się za końcem pojemności lub za NUL. Puste zmienne mają wartość `''`.
Po sprawdzeniu kodowania tekst kończy się na pierwszym NUL, a nadmiar jest obcinany
z prawej do pojemności zmiennej. Dotyczy to inicjalizacji, przypisań, parametrów,
wyników i komórek Pythona. Nie emulujemy bajtów bufora za kończącym NUL.

```iecst
FUNCTION F_Label : STRING(8)
VAR CONSTANT capacity : INT := 12; END_VAR
VAR name : STRING(capacity) := 'caf$E9'; END_VAR
F_Label := CONCAT(name, '-ready');  // Wynik: 'café-rea'.
END_FUNCTION
```

Literały zachowują wielkość liter, np. `'DriveA'` lub `STRING#'DriveA'`.
Obsługują `$L`/`$N` (LF), `$R` (CR), `$T` (tabulator), `$P` (form feed),
`$$`, `$'` oraz dwie cyfry szesnastkowe, np. `$E9` i `$00`.
Litery w sekwencjach specjalnych mogą być małe lub wielkie. Surowe znaki końca
wiersza wewnątrz literału i błędne sekwencje powodują błąd parsowania.

Wszystkie sześć porównań (`=`, `<>`, `<`, `<=`, `>`, `>=`) działa leksykograficznie,
z rozróżnianiem wielkości liter, także dla różnych pojemności. Do łączenia tekstu
służy `CONCAT`; operator `+` nie obsługuje tekstu. `SEL` i `MUX` zachowują leniwe
wykonanie i wybierają pojemność wyniku równą największej z pojemności alternatyw.

**Standardowe funkcje tekstowe:** każdy argument tekstowy przechodzi przez
`STRING(255)`, a każdy wynik tekstowy także ma pojemność 255. `LEN` i `FIND`
zwracają `INT`. Dłuższe zmienne mogą być przechowywane i kopiowane, ale te funkcje
przetwarzają tylko pierwsze 255 bajtów. Argumenty mogą być pozycyjne albo nazwane;
nie można mieszać obu form.

| Funkcja i nazwy argumentów | Zachowanie |
|---|---|
| `LEN(STR)` | Długość tekstu. |
| `LEFT(STR, SIZE)` / `RIGHT(STR, SIZE)` | Pierwsze/ostatnie SIZE bajtów; zero daje pusty tekst. |
| `MID(STR, LEN, POS)` | LEN bajtów od pozycji POS, liczonej od 1. |
| `CONCAT(STR1, STR2)` | Połączenie dwóch tekstów. |
| `FIND(STR1, STR2)` | Pierwsza pozycja od 1; brak wyniku daje 0, pusty wzorzec daje 1. |
| `INSERT(STR1, STR2, POS)` | Wstawienie po POS bajtach; POS=0 wstawia na początku. |
| `DELETE(STR, LEN, POS)` | Usunięcie LEN bajtów od pozycji POS, liczonej od 1. |
| `REPLACE(STR1, STR2, L, P)` | Zastąpienie L bajtów od pozycji P całym STR2. |

Rozmiary i pozycje muszą mieścić się w `INT` i być nieujemne; `MID`, `DELETE`
i `REPLACE` wymagają pozycji co najmniej 1. Błędne wartości zgłaszają
`ExecutionError`. Zbyt duży rozmiar wybiera dostępny tekst. Pozycja za końcem daje
pusty wynik dla `MID`, pozostawia tekst dla `DELETE`, a dla `INSERT`/`REPLACE`
dopisuje tekst na końcu. `REPLACE` z L=0 wstawia tekst przed P.
Są to jawne reguły tego profilu dla przypadków brzegowych.

**Konwersje:** obsługiwane są `BOOL`, `INT`, `UINT`, `DINT`, `UDINT`, `BYTE`,
`WORD`, `DWORD` w obu kierunkach z `STRING`: np. `DINT_TO_STRING`,
`STRING_TO_DINT`, `BOOL_TO_STRING`, `STRING_TO_BOOL`, a także `TO_STRING`
i odpowiednie `TO_<typ>`. Wynik tekstowy ma pojemność 255. Liczby są formatowane
dziesiętnie, BOOL jako `TRUE`/`FALSE`. Typowane konwersje liczbowe sprawdzają
najpierw zakres typu źródłowego, zgodnie z istniejącymi konwersjami.

```iecst
FUNCTION F_SpeedText : STRING(20)
F_SpeedText := DINT_TO_STRING(STRING_TO_DINT('-12_345'));
END_FUNCTION
```

Konwersja tekstu do liczby wymaga kompletnego zapisu dziesiętnego: opcjonalny
znak `+`/`-`, cyfry ASCII i ewentualne podkreślenia wyłącznie między cyframi.
Spacje, sufiksy, zapis `16#`, pusty tekst oraz przekroczenie zakresu powodują
`ExecutionError`; liczby nie zawijają się. Konwersja czyta cały zapis w zadeklarowanej
pojemności, bez limitu 255 właściwego dla funkcji tekstowych.
To celowo bardziej rygorystyczny profil niż konwersje TwinCAT akceptujące sufiksy.
`STRING_TO_BOOL` zwraca TRUE tylko dla dokładnie `'TRUE'` albo `'true'`;
`'True'` i pozostałe teksty dają FALSE.

`VAR_INPUT`, wyniki i wiązania `VAR_OUTPUT =>` kopiują tekst do pojemności celu.
`VAR_IN_OUT` wymaga **dokładnie tej samej pojemności**, również w API Pythona;
alias typu jest przezroczysty. Całe tablice także wymagają zgodnych typów i granic.
Wcześniej pobrane komórki pól/elementów pozostają aktualne po zastąpieniu struktury
lub tablicy.

```python
from tc_emulator import Runtime, StringType

runtime = Runtime.from_files(["examples/strings.st"])
message = runtime.call("F_AlarmText", device="DriveA", code=42, active=True).value
assert message == "DriveA: alarm 42 [TRUE]"

command = runtime.instantiate("FB_SpeedCommand")
command.call(command="SPEED=120")
assert command.output("accepted") is True
assert command.output("speed") == 120

label = runtime.cell(StringType(16), "Batch")  # Także runtime.cell("STRING(16)", ...).
runtime.call("F_AppendLabel", label=label, suffix="-A")
assert label.value == "Batch-A"
```

`Runtime.cell()` przyjmuje opis typu z dosłowną pojemnością; wyrażenia takie jak
`STRING(1+2)` i lokalne nazwy stałych są obsługiwane w deklaracjach ST, nie w tym API.
`WSTRING`, UTF-8, indeksowanie bajtów tekstu oraz konwersje tekstowe REAL/LREAL/TIME
i enumów pozostają poza zakresem.

Podstawy składni i biblioteki opisuje Beckhoff:
[STRING](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529410443.html),
[literały tekstowe](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529327243.html),
[funkcje tekstowe](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/7647318155.html),
[konwersje](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529074315.html).

## PROGRAM, GVL i cykle PLC (v0.8)

Każdy `PROGRAM` ma jeden trwały stan na obiekt `Runtime`. Kolejne skany i wywołania
tego samego programu z innego programu lub FB korzystają z tych samych zmiennych.
Inny `Runtime` tworzy niezależny stan i zegar. `VAR_TEMP` w programie jest
inicjalizowane przy każdym wywołaniu. Programy obsługują `VAR`, `VAR CONSTANT`,
`VAR_INPUT`, `VAR_OUTPUT` i `VAR_TEMP`; nie mają wyniku funkcji ani `VAR_IN_OUT`.

```iecst
VAR_GLOBAL
    total : DINT;
END_VAR

PROGRAM MAIN
VAR count : DINT; END_VAR
count := count + 1;
GVL.total := count;
END_PROGRAM
```

`Runtime.from_source()` nadaje sekcjom globalnym domyślną nazwę `GVL`.
Można ją zmienić przez `gvl_name="GVL_IO"`. Wszystkie sekcje `VAR_GLOBAL` i
`VAR_GLOBAL CONSTANT` z jednego źródła tworzą jedną listę. W pliku `.st` nazwa
listy pochodzi z nazwy pliku bez rozszerzenia, a w `.TcGVL` z atrybutu XML `Name`.
Nie dodajemy osobnego słowa kluczowego ST do nazywania listy.

GVL może zawierać wszystkie obsługiwane typy wartościowe oraz zwykłe instancje FB.
Globalna instancja FB jest współdzielona przez wszystkich wywołujących. Funkcje,
FB i programy mogą czytać i zapisywać GVL. Importowane deklaracje są rozwiązywane
razem, niezależnie od kolejności plików, również gdy globalna stała definiuje granice
tablicy, pojemność `STRING`, inicjalizację lub etykietę `CASE`.

**Widoczność nazw:**

- Lokalna zmienna lub wynik funkcji ma pierwszeństwo, także przed nazwą GVL.
- `GVL_IO.start` wskazuje konkretną listę; `MAIN.count` wskazuje stan programu.
- Sama nazwa globalnej zmiennej jest dozwolona, jeśli jednoznacznie wskazuje jedną
  listę bez `qualified_only`. Niejednoznaczność jest błędem walidacji.
- `{attribute 'qualified_only'}` przed pierwszą sekcją `VAR_GLOBAL` wymaga nazwy
  listy także w inicjalizatorach tej samej GVL. Inne atrybuty są odrzucane.
- Prywatne pola FB zachowują dotychczasową ochronę; z zewnątrz dostępne są ich
  wejścia/wyjścia. Pola `VAR_TEMP` programu nie są dostępne przez `MAIN.field`.

`VAR_GLOBAL CONSTANT` wymaga inicjalizatora i pozostaje tylko do odczytu.
Dotyczy to także pól struktur, elementów tablic i widoków bitów. Cykle zależności
stałych, odwołania do zmiennych mutowalnych w inicjalizatorach i wywołania funkcji
w wyrażeniach stałych są odrzucane podczas wczytywania.

**API cyklu:**

| Wywołanie | Działanie |
|---|---|
| `runtime.scan("MAIN")` | Jeden skan programu w bieżącym czasie. |
| `runtime.scan("Control", "Diagnostics")` | Programy kolejno, jeden wspólny czas i budżet instrukcji. |
| `runtime.run_cycles("MAIN", cycles=100, period_ms=10)` | 100 skanów; po każdym udanym skanie przesunięcie czasu o 10 ms. |
| `runtime.global_cell("GVL_IO", "start")` | Żywa, typowana komórka zmiennej globalnej. |
| `runtime.program_cell("MAIN", "count")` | Żywa komórka trwałej zmiennej programu. |

`scan()` nie przesuwa czasu. `advance_time()` nadal przesuwa wyłącznie zegar i niczego
nie wykonuje. `run_cycles()` wykonuje cały cykl, a następnie przesuwa czas **raz**;
nie czeka i nie tworzy wątku. Dla początkowego t=0, 100 cykli po 10 ms wykonuje kod
w chwilach 0, 10, ..., 990 ms i pozostawia zegar na 1000 ms. Timer TON uruchomiony
w pierwszym cyklu z PT=T#1s osiągnie Q=TRUE dopiero podczas skanu w chwili 1000 ms.

Programy przekazuje się jako kolejne argumenty, np. `scan("A", "B")`.
Lista musi być niepusta i bez powtórzeń nazw; wielkość liter nie ma znaczenia.
`cycles` musi być nieujemnym `int`, a `period_ms` dodatnim `int`; BOOL jest odrzucany.
Przy cycles=0 parametry są sprawdzane, lecz kod i zegar pozostają bez zmian.
Nieprawidłowe nazwy lub parametry nie wykonują żadnego programu i nie uszkadzają Runtime.

Budżet `max_steps` jest wspólny dla wszystkich programów i zagnieżdżonych wywołań
w jednym skanie; każdy kolejny cykl otrzymuje nowy budżet. Błąd wykonania zachowuje
dotychczasowe zapisy, zatrzymuje pozostałe programy i ustawia Runtime w stanie awarii.
Nie przesuwa zegara za nieudany cykl; czas ukończonych wcześniejszych cykli pozostaje.
Odczyt i pobieranie komórek diagnostycznych nadal działa, zapis i wykonanie są blokowane.

`global_cell()` i `program_cell()` przyjmują nazwę pojedynczej zmiennej wartościowej;
dalszy dostęp odbywa się przez `.field()`, `.element()` i `.bit()`.
Właściwość `.read_only` informuje o stałej. Próba zapisu albo przekazania takiej
komórki jako `VAR_IN_OUT` zgłasza `ArgumentError`. Komórki pozostają aktualne po
zastąpieniu całej struktury lub tablicy. Globalny FB jako całość nie jest komórką
wartościową; wywołuje się go z ST, np. `GVL_Devices.counter()`.

Programy i FB mogą wywołać program, np. `Worker(step := 3, count => result)`.
Pominięte wejścia programu zachowują wartości. Funkcja nie może bezpośrednio
wywołać programu; program nie jest wyrażeniem. `Runtime.call()` nadal służy do
FUNCTION, a `instantiate()` do tworzenia nowych instancji FUNCTION_BLOCK.

**Przykład przenośnika:** pliki `examples/conveyor/MAIN.TcPOU`, `GVL_IO.TcGVL`
i `GVL_Config.TcGVL` zawierają sterowanie start/stop, blokadę osłony, sekundowe
opóźnienie rozruchu TON, zliczanie zboczy czujnika i komunikat alarmowy.
Stop i otwarta osłona mają pierwszeństwo przed startem oraz kasują żądanie ruchu.
Wejście start jest poleceniem poziomowym; po jego przyjęciu żądanie pozostaje
zatrzaśnięte do stopu/blokady. Czujnik jest próbkowany także podczas postoju,
a zliczanie działa tylko przy włączonym napędzie; reset licznika ma pierwszeństwo.

```python
from pathlib import Path
from tc_emulator import Runtime

source = Path("examples/conveyor")
runtime = Runtime.from_files(
    [
        source / "MAIN.TcPOU",
        source / "GVL_IO.TcGVL",
        source / "GVL_Config.TcGVL",
    ]
)
start = runtime.global_cell("GVL_IO", "start")
running = runtime.global_cell("GVL_IO", "motorRunning")
start.value = True
runtime.scan("MAIN")  # TON startuje w chwili 0.
start.value = False
runtime.advance_time(milliseconds=1000)
runtime.scan("MAIN")
assert running.value is True

runtime.global_cell("GVL_IO", "productSensor").value = True
runtime.scan("MAIN")
assert runtime.global_cell("GVL_IO", "productCount").value == 1

runtime.global_cell("GVL_IO", "guardClosed").value = False
runtime.scan("MAIN")
assert running.value is False
assert runtime.global_cell("GVL_IO", "alarm").value == "Guard open"
```

`.TcGVL` jest importowany jako ścisły, deklaracyjny XML: jeden element GVL z nazwą,
jedna sekcja Declaration, bez kodu wykonywalnego i nieznanych obiektów semantycznych.
Pełny import `.plcproj`, wielozadaniowy scheduler, mapowanie I/O przez `AT`,
RETAIN/PERSISTENT, ADS/EtherCAT i zegar czasu rzeczywistego pozostają poza zakresem.

Zachowanie programów i przestrzeni nazw opisuje Beckhoff:
[PROGRAM](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2530274187.html),
[GVL](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2530218891.html),
[nazwy GVL](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529197963.html).

## Metody bloków funkcyjnych (v0.9)

Metoda działa na konkretnej instancji FB. Wywołanie jej nie wykonuje głównego
ciała FB ani nie przesuwa czasu. Zwykłe zmienne lokalne metody, jej wejścia,
wyjścia i wynik powstają od nowa przy każdym wywołaniu. Stan zapisany w polach
FB pozostaje trwały. Dotyczy to również timerów: timer lokalny metody jest
tworzony od nowa, więc timer odmierzający czas między wywołaniami należy
zadeklarować w FB, jak w przykładzie przenośnika.

W pliku `.st` sekcje metod umieszczamy po głównym ciele FB, przed
`END_FUNCTION_BLOCK`. Każda kończy się `END_METHOD`:

```python
from tc_emulator import Runtime

runtime = Runtime.from_source("""
FUNCTION_BLOCK FB_Total
VAR_OUTPUT total : DINT; END_VAR

METHOD PUBLIC Add : DINT
VAR_INPUT amount : DINT := 1; END_VAR
total := total + amount;
Add := total;
END_METHOD

METHOD PUBLIC Reset
Clear();
END_METHOD

METHOD PRIVATE Clear
total := 0;
END_METHOD
END_FUNCTION_BLOCK
""")

counter = runtime.instantiate("FB_Total")
assert counter.call_method("Add", amount=4).value == 4
assert counter.call_method("add").value == 5
assert counter.call_method("Reset").value is None
assert counter.output("total") == 0
```

`PUBLIC` jest domyślne. `PRIVATE` dopuszcza wywołania z ciała deklarującego FB
i jego metod; próba wywołania takiej metody z Pythona daje `ArgumentError`.
Ze ST można wywoływać `fb.Add(amount := 2)` oraz używać wyniku w wyrażeniu.
Wewnątrz FB można użyć krótkiej nazwy, np. `Clear()`.

Metody obsługują `VAR`, `VAR CONSTANT`, `VAR_INPUT`, `VAR_OUTPUT` i `VAR_IN_OUT`.
Wejście bez inicjalizatora jest wymagane; wejście z jawnym inicjalizatorem można
pominąć — wtedy przy każdym wywołaniu otrzymuje wartość początkową. To profil
metod TwinCAT 3.1 build 4026. `VAR_IN_OUT` jest zawsze wymagane: w Pythonie
przekaż `runtime.cell(...)` o dokładnie zgodnym typie, także dla struktur/tablic.
W ST obowiązują reguły argumentów funkcji, w tym wyjścia wiązane przez `=>`.

`call_method(name, /, **inputs)` zwraca `CallResult`: `.value` to wynik lub
`None` dla metody bez typu zwrotnego; `.outputs` jest niemodyfikowalną migawką
dodatkowych wyjść. Nazwy są niewrażliwe na wielkość liter. Błędne argumenty
są odrzucane przed zmianą stanu FB. Błąd wykonania zachowuje częściowe zmiany
i blokuje dalsze wykonywanie tego runtime'u, tak samo jak błąd funkcji lub skanu.

Import `.TcPOU` wczytuje osobne elementy `Method` wraz z deklaracjami i kodem ST.
Błędy wskazują nazwę metody i linię w jej `Declaration` lub `Implementation`.
Wszystkie metody są sprawdzane, także niewywoływane. Metody dzielą budżet kroków,
limit głębokości wywołań i wirtualny zegar z wywołującym kodem.

**Przenośnik z metodami:** `examples/conveyor/FB_Conveyor.TcPOU` udostępnia
`Start`, `Stop`, `Reset` (zerowanie licznika), `Update` i `IsRunning`.
Prywatna `CountProduct` zlicza zbocza czujnika. `MAIN_Methods.TcPOU` używa tego
FB z istniejącymi `GVL_IO.TcGVL` i `GVL_Config.TcGVL`; oryginalny `MAIN.TcPOU`
z v0.8 pozostaje osobnym przykładem.

```python
from pathlib import Path

from tc_emulator import Runtime

source = Path("examples/conveyor")
runtime = Runtime.from_files([source / "FB_Conveyor.TcPOU"])
controller = runtime.instantiate("FB_Conveyor")
controller.call_method("Start", delay=250)  # TIME z Pythona: milisekundy.
controller.call_method("Update", guardClosed=True)
assert controller.call_method("IsRunning").value is False
runtime.advance_time(250)
controller.call_method("Update", guardClosed=True)
assert controller.call_method("IsRunning").value is True
controller.call_method("Stop")
assert controller.call_method("IsRunning").value is False
```

Testy `examples/test_conveyor_methods.py` pokazują także pełne skany PLC,
pierwszeństwo interlocków, niezależne instancje i reset licznika produktów.

Metody pozostają ograniczone do FB. W v0.15 specjalne `FB_init` wykonuje się
podczas tworzenia instancji; `FB_reinit`/`FB_exit` pozostają poza zakresem.
Kolejne sekcje opisują `THIS^`, `VAR_INST`, właściwości, interfejsy i dziedziczenie.
Metoda nie może odwoływać się do `VAR_TEMP` ani `VAR_IN_OUT` właściciela;
własne `VAR_IN_OUT` metody jest obsługiwane. Ograniczenie dotyczące właściciela
zapobiega używaniu zapamiętanego powiązania z wcześniejszego wywołania FB.
Rekurencyjne cykle wywołań są odrzucane podczas walidacji.

Semantyka referencyjna: [metody TwinCAT](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2530307467.html)
i [wywoływanie metod](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2527348875.html).

## Tablice FB i otwarte parametry tablicowe (v0.10)

Stała tablica FB przechowuje oddzielną instancję w każdym elemencie, np.
`conveyors : ARRAY[1..3] OF FB_Conveyor` lub `timers : ARRAY[-2..2] OF TON`.
Obsługiwane są również tablice wielowymiarowe. Można wywoływać `timers[i](...)`,
`conveyors[i].Start(...)`, odczytywać wyjścia i zapisywać wejścia.
Odbiorca wywołania jest wybierany raz, przed obliczeniem argumentów.

Instancje w PROGRAM, GVL i zwykłym VAR bloku FB zachowują stan między cyklami.
Tablice lokalne funkcji/metody oraz VAR_TEMP są tworzone od nowa zgodnie
z czasem życia ich zakresu. `.inspect()` zwraca odłączone migawki tablic FB
jako zagnieżdżone tuple zawierające słowniki stanu.

Python udostępnia istniejące instancje przez:

- `runtime.program_fb("MAIN", "conveyors", 2)` — element tablicy w PROGRAM.
- `runtime.global_fb("GVL", "timers", -1)` — element tablicy w GVL.
- `parent.fb("children", 1, 2)` — element tablicy wewnątrz FB.

Dla pojedynczego FB pomiń indeksy; dla zagnieżdżonych FB wywołuj kolejne `.fb()`.
Nazwy oznaczają pojedyncze deklaracje, bez wyrażeń ST. Indeksy są indeksami ST,
nie pozycjami Pythona; BOOL nie jest indeksem. Zwracany `FBHandle` obsługuje
istniejące `call`, `call_method`, `set_input`, `output` i `inspect`.
Wybór nie tworzy kopii. Nie można pobrać uchwytu do VAR_TEMP.

**Linia trzech przenośników** korzysta z FB z v0.9, trzech opóźnień
100/250/500 ms i osobnych czujników, interlocków oraz liczników produktów.
Pliki są w `examples/conveyor_line`, a scenariusze w `examples/test_conveyor_line.py`.

```python
from pathlib import Path

from tc_emulator import Runtime

source = Path("examples/conveyor_line")
runtime = Runtime.from_files(
    [
        source / "MAIN_Line.TcPOU",
        source / "GVL_Line.TcGVL",
        source / "F_Total.TcPOU",
        Path("examples/conveyor/FB_Conveyor.TcPOU"),
    ]
)

second = runtime.program_fb("MAIN_Line", "conveyors", 2)
second.call_method("Start", delay=250)
runtime.scan("MAIN_Line")
runtime.advance_time(250)
runtime.scan("MAIN_Line")
assert second.call_method("IsRunning").value is True
assert runtime.global_cell("GVL_Line", "motorRunning").value == (False, True, False)
```

`ARRAY[*] OF T` i `ARRAY[*, *] OF T` są obsługiwane jako bezpośrednie
parametry `VAR_IN_OUT` funkcji, FB i metod. Wszystkie wymiary są otwarte.
Typ elementu oraz liczba wymiarów muszą się zgadzać; granice mogą się różnić.
Alias zachowuje faktyczne granice i pamięć argumentu, również po przekazaniu
do następnej funkcji. Python wymaga istniejącego `Cell` tego samego runtime'u:

```python
counts = runtime.cell("ARRAY[-2..0] OF UDINT", [5, 8, 13])
assert runtime.call("F_Total", counts=counts).value == 26
```

`F_Total` iteruje od `LOWER_BOUND(counts, 1)` do `UPPER_BOUND(counts, 1)`.
Operatory przyjmują lokalizację tablicy i numer wymiaru od 1 do liczby wymiarów;
zwracają DINT. Działają dla stałych tablic wartości/FB i otwartych parametrów,
w kodzie wykonywalnym. Numer wymiaru może być wyrażeniem; błędny numer powoduje
`ExecutionError`. Obsługa zwykłych tablic odpowiada profilowi TwinCAT build 4026.

Otwarte parametry obsługują indeksowanie, operatory granic i dalsze przekazywanie
do otwartych parametrów. Nie obsługują operacji wartościowych na całej tablicy,
inicjalizatorów, zwracania całej tablicy ani przekazywania do parametru ze stałymi
granicami. Tablice FB nie są wartościami: nie obsługujemy ich kopiowania,
inicjalizatorów, umieszczania w STRUCT/aliasach ani przekazywania przez VAR_IN_OUT.
Otwarte tablice FB, mieszane wymiary `ARRAY[*, 1..3]` i `FB_init` pozostają poza zakresem.
Deklaracyjne wyrażenia stałe nadal nie dopuszczają wywołań, również operatorów granic.

Walidacja uwzględnia mnożenie liczby instancji przez rozmiary tablic: granice
rozbudowanej pamięci jednego POU to 10 000 zagnieżdżonych instancji FB oraz
1 000 000 wartości skalarnych. Aliasy VAR_IN_OUT nie tworzą własnej pamięci.

Semantyka referencyjna: [tablice stałe i instancje FB](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/8825253771.html),
[otwarte parametry i granice](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/8825257611.html),
[operatory dla tablic stałych od build 4026](https://infosys.beckhoff.com/content/1031/tc3_plc_intro/21269831691.html).

## Właściwości, THIS^ i VAR_INST (v0.11)

Właściwości FB obsługują typy skalarne, `TIME`, `STRING(n)`, enumy i aliasy
tych typów. Odczyt `fb.Speed` wykonuje `GET`, a zapis `fb.Speed := 0.75`
wykonuje `SET`. Brak jednego akcesora oznacza właściwość tylko do odczytu
lub tylko do zapisu. `PUBLIC` jest domyślne; `PRIVATE` ogranicza dostęp do
kodu deklarującego FB. Akcesor może dodatkowo zawęzić dostęp do właściwości.

Poniższy zapis łączy obiekty TwinCAT w jednym pliku `.st`. `GET/END_GET`,
`SET/END_SET` i `END_PROPERTY` są formatem tekstowym emulatora; w `.TcPOU`
importujemy oddzielne obiekty `Property`, `Get` i `Set` z kodem ST.

```python
from tc_emulator import Runtime

runtime = Runtime.from_source("""
FUNCTION_BLOCK FB_Setpoint
VAR
    speed : LREAL := 0.5;
END_VAR

PROPERTY PUBLIC SpeedSetpoint : LREAL
GET
    SpeedSetpoint := THIS^.speed;
END_GET
SET
    THIS^.speed := LIMIT(0.0, SpeedSetpoint, 1.0);
END_SET
END_PROPERTY

METHOD PUBLIC Tick : UDINT
VAR_INST
    calls : UDINT;
END_VAR
calls := calls + 1;
Tick := calls;
END_METHOD
END_FUNCTION_BLOCK
""")

controller = runtime.instantiate("FB_Setpoint")
controller.set_property("SpeedSetpoint", 2.0)
assert controller.get_property("SpeedSetpoint") == 1.0
assert controller.call_method("Tick").value == 1
assert controller.call_method("Tick").value == 2
assert runtime.instantiate("FB_Setpoint").call_method("Tick").value == 1
```

`FBHandle.get_property(name, /)` zwraca wartość, a
`set_property(name, value, /)` wykonuje setter i zwraca `None`. Nazwy są
niewrażliwe na wielkość liter. Błędna nazwa, dostęp, typ lub zakres wartości
powodują `ArgumentError` przed wykonaniem akcesora. Kontrola typu poprzedza
setter, ale prawidłową wartość setter może przekształcić, np. ograniczyć prędkość.
API działa również na uchwytach z `program_fb()`, `global_fb()` i `fb()`.

Getter i setter wykonują ST przy każdym dostępie, korzystając ze wspólnego
budżetu kroków i wirtualnego czasu. Indeksowana instancja jest wybierana raz,
przed obliczeniem prawej strony przypisania. Sam zapis nie wykonuje gettera.
Błąd wykonania zachowuje częściowe zmiany i blokuje dalsze wykonywanie runtime'u,
w tym `get_property()`. `inspect()` nie uruchamia getterów i nadal pozwala
odczytać odłączoną kopię zapisanego stanu po błędzie. Stan `VAR_INST` jest
dostępny w niej pod kluczem `$VAR_INST`, według nazw metod zapisanych wielkimi literami.

`THIS^.field`, `THIS^.Method()` i `THIS^.Property` wskazują bieżącą instancję FB.
Pozwala to odwołać się do pola przesłoniętego przez lokalną zmienną. Własne pola
prywatne są dostępne, ale prywatne pola zagnieżdżonego FB pozostają zamknięte.
Metody i akcesory nadal nie mają dostępu do `VAR_TEMP` i `VAR_IN_OUT` właściciela.
Samo `THIS`, przekazywanie wskaźnika i ogólna dereferencja nie są obsługiwane.

`VAR_INST` jest dozwolone wyłącznie w metodzie FB. Pamięć powstaje razem
z instancją właściciela i jest oddzielna dla każdej metody oraz każdego FB,
również elementu tablicy. Obsługiwane są wartości, struktury, tablice oraz
instancje FB, w tym timery i tablice FB. Zwykłe `VAR` metody pozostaje świeże
przy każdym wywołaniu. Inicjalizatory i granice typów `VAR_INST` korzystają
ze stałych widocznych dla właściciela, bez zależności od wejść i lokalnych
stałych metody. Modyfikatory `CONSTANT`, `RETAIN` i `PERSISTENT` przy `VAR_INST`
są odrzucane. Pamięć i cykle zagnieżdżeń uwzględniają te zmienne przed alokacją.

W tym profilu lokalne `VAR`/`VAR CONSTANT` z deklaracji właściwości oraz akcesora
są inicjalizowane przy każdym dostępie. Typ właściwości oraz typy, granice i
inicjalizatory jej zmiennych nagłówkowych korzystają ze stałych nagłówka i
właściciela FB. Lokalne stałe GET/SET nie zmieniają tych deklaracji; mogą
przesłaniać nazwy właściciela we własnych deklaracjach i kodzie akcesora.
Nazwy zmiennych nagłówka i akcesora nie mogą się powtarzać. Nazwa właściwości wewnątrz akcesora oznacza jego lokalny wynik
(`GET`) lub przypisywaną wartość (`SET`). `THIS^.NazwaWłaściwości` wykonuje
akcesor ponownie; rekurencyjne cykle są odrzucane podczas walidacji.

Właściwość nie jest komórką `Cell`: nie można przekazać jej przez `VAR_IN_OUT`,
użyć jako licznika `FOR`, celu `=>` ani zapisywać jej pojedynczych bitów.
Właściwości struktur/tablic/FB i `REFERENCE TO`, dodatkowe parametry akcesorów,
`VAR_INST` w akcesorach oraz właściwości PROGRAM pozostają poza zakresem.

**Linia trzech przenośników:** `examples/conveyor_properties/` zawiera
rozszerzony przykład. `SpeedSetpoint` ogranicza prędkość do 0–1, a `Running`,
`ActiveSpeed`, `ProductCount` i `Alarm` udostępniają stan tylko do odczytu.
Metoda `Update` zachowuje timer `TON`, detektor `R_TRIG` i licznik wywołań
w `VAR_INST`. Program używa indeksowanych właściwości trzech niezależnych FB.

Uruchomienie z katalogu projektu:

```python
from pathlib import Path
from tc_emulator import Runtime

source = Path("examples/conveyor_properties")
runtime = Runtime.from_files(sorted(source.glob("*.TcPOU")) + sorted(source.glob("*.TcGVL")))
second = runtime.program_fb("MAIN_Line", "conveyors", 2)
second.set_property("SpeedSetpoint", 0.75)
second.call_method("Start", delay=250)
runtime.scan("MAIN_Line")
assert second.get_property("Running") is False
runtime.advance_time(250)
runtime.scan("MAIN_Line")
assert second.get_property("Running") is True
assert runtime.global_cell("GVL_Line", "actualSpeed").value == (0.0, 0.75, 0.0)
```

`examples/test_conveyor_properties.py` sprawdza konfigurację ze ST i Pythona,
niezależne opóźnienia, zatrzymanie i ponowny start oraz zliczanie produktów.

Semantyka referencyjna: [właściwości](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2530335371.html),
[THIS](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528843147.html),
[VAR_INST](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528798091.html).

## Interfejsy i atrapy zależności (v0.12)

`INTERFACE` deklaruje publiczne metody i właściwości, a `IMPLEMENTS` zobowiązuje
FB do ich implementacji. Zmienna interfejsowa wskazuje istniejącą instancję;
nie kopiuje jej stanu. Jeden FB może implementować kilka interfejsów.
W łączonym pliku `.st` kontrakt zapisujemy tak:

```iecst
INTERFACE I_Motor
    METHOD Update
    VAR_INPUT
        run : BOOL;
        delay : TIME;
    END_VAR
    END_METHOD
    PROPERTY Running : BOOL
        GET
        END_GET
    END_PROPERTY
END_INTERFACE

FUNCTION_BLOCK FB_Controller
VAR_INPUT
    motor : I_Motor;
END_VAR
IF motor <> 0 THEN
    motor.Update(run := TRUE, delay := T#100ms);
END_IF;
END_FUNCTION_BLOCK
```

Implementujący FB zaczyna się od `FUNCTION_BLOCK FB_MotorSim IMPLEMENTS I_Motor`.
Kontrakty nie zawierają implementacji ani zmiennych lokalnych. Wymagamy zgodnych
nazw, kolejności, kierunków i rozstrzygniętych typów parametrów oraz typu wyniku.
Domyślne wartości wejść i ich opcjonalność również muszą się zgadzać. Właściwość
musi udostępniać wymagane publiczne akcesory; dodatkowy setter implementacji
nie staje się dostępny przez interfejs deklarujący wyłącznie GET. Wywołanie
wybiera bieżącą instancję raz, przed obliczeniem argumentów lub wartości dla SET.

Obsługujemy bezpośrednie zmienne interfejsowe w `VAR`, `VAR_INPUT`, GVL,
`VAR_TEMP` FB/PROGRAM i `VAR_INST` metod. Domyślna wartość to null, zapisywane
jako dosłowne całkowite `0`. ST pozwala przypisać implementujący FB, zmienną tego
samego interfejsu, interfejs pochodny do bazowego albo `0`, a także porównać
interfejs z `0` przez `=`/`<>`.
Przypisanie między zmiennymi kopiuje wskazywaną instancję, więc późniejsze
przestawienie jednej zmiennej nie zmienia drugiej. Typy interfejsów są nominalne:
identyczne zestawy metod nie wystarczają do przypisania między niepowiązanymi interfejsami.

`Runtime.call()`, `FBHandle.call()`, `call_method()` i `set_input()` przyjmują
na wejściu interfejsowym `FBHandle` z tego samego Runtime albo dokładnie całkowite
`0`. Błędny typ, nieimplementujący FB, uchwyt z innego Runtime, `None` i `True`
powodują `ArgumentError` przed wykonaniem ST i zmianą wejść. Uchwyty uzyskane przez
`instantiate()`, `program_fb()`, `global_fb()` i `fb()` zachowują tożsamość instancji.
Interfejs nie jest `Cell`; selektory komórek nie udostępniają go do modyfikacji.

**Przykład trzech przenośników:** `examples/conveyor_interfaces/` zawiera
`I_Motor.TcIO`, silnik symulowany, atrapę `FB_MotorFake`, sterownik przenośnika,
PROGRAM i GVL. Przenośnik steruje silnikiem wyłącznie przez `I_Motor`.
Pierwszy skan wiąże trzy niezależne silniki, a Python może następnie podmienić
zależność wybranego przenośnika. Powiązanie zatrzymuje poprzedni silnik i wymaga
jawnego ponownego startu. Awaria atrapy zatrzymuje tylko jej przenośnik;
usunięcie awarii również wymaga nowego polecenia startu.

Uruchomienie z katalogu projektu:

```python
from pathlib import Path
from tc_emulator import Runtime

source = Path("examples/conveyor_interfaces")
runtime = Runtime.from_files(sorted(source.glob("*.Tc*")))
runtime.scan("MAIN_Line")  # Jednorazowe powiązanie domyślnych silników.
fake = runtime.instantiate("FB_MotorFake")
second = runtime.program_fb("MAIN_Line", "conveyors", 2)
second.call_method("BindMotor", motor=fake)
second.set_property("SpeedSetpoint", 0.75)
second.call_method("Start", delay=100)
runtime.scan("MAIN_Line")
runtime.advance_time(100)  # Wirtualne milisekundy, bez czekania.
runtime.scan("MAIN_Line")
assert second.get_property("Running") is True
assert fake.get_property("ActualSpeed") == 0.75

fake.set_input("fault", True)
runtime.scan("MAIN_Line")
assert second.get_property("Running") is False
assert second.get_property("Alarm") == "Motor fault"
```

Testy w `examples/test_conveyor_interfaces.py` obejmują niezależne opóźnienia
100/250/500 ms, podmianę silnika, izolację awarii, restart, odłączenie interfejsu,
nieprawidłowe uchwyty oraz niezależne zliczanie produktów.

`.TcIO` obsługuje natywne `TcPlcObject/Itf` z deklaracjami Method i Property/Get/Set.
Sekcje Implementation są odrzucane; kolejność plików `.TcIO`/`.TcPOU` nie ma znaczenia.
Od v0.17 interfejsy obsługują wielobazowe `EXTENDS` i bezpośrednie tablice
stałowymiarowe opisane poniżej. Poza profilem pozostają `__QUERYINTERFACE`,
niejawne konwersje w dół, wyniki interfejsowe, `VAR_OUTPUT`/`VAR_IN_OUT` typu
interfejsowego, pola STRUCT, aliasy i stałe interfejsowe. Właściwości interfejsu
mają zakres typów wartościowych taki jak właściwości FB z v0.11.

Runtime sprawdza czas życia referencji: FB lokalny funkcji/metody/akcesora lub
`VAR_TEMP` przestaje być ważny po zakończeniu wywołania, także gdy wskazuje go
zachowana zmienna interfejsowa. Dotyczy to również jego zagnieżdżonych instancji.
`VAR_INST` trwa tak długo jak właściciel FB. Wywołanie przez null albo użycie
wygasłej referencji, także porównanie jej z `0`, powoduje `ExecutionError` i fault
Runtime. To jawny profil emulatora; nie odtwarzamy niekontrolowanych wskaźników.
`inspect()` pokazuje odłączone metadane `interface`, `target`, `valid`, bez
uruchamiania getterów i bez rekurencyjnego przechodzenia przez referencje.

Walidacja rekurencji uwzględnia wszystkie wczytane implementacje kontraktu.
Może zatem odrzucić cykl nawet wtedy, gdy konkretne wiązania wykonawcze go nie
osiągnęłyby. Referencje nie zwiększają liczby instancji FB; każde pole interfejsowe
zajmuje jedną pozycję w limicie pamięci skalarnej.

Semantyka referencyjna: [deklaracja interfejsu](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/4256428299.html)
i [zmienne interfejsowe](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/5680748299.html).

## Dziedziczenie i kolekcje interfejsów (v0.17)

`INTERFACE I_Conveyor EXTENDS I_Command, I_Status` łączy odziedziczone kontrakty;
`I_Reversible EXTENDS I_Conveyor` dodaje właściwość `Reverse`. Kolejność deklaracji
nie ma znaczenia. Diament z tym samym kontraktem jest akceptowany, a sprzeczne
metody, właściwości, akcesory lub wartości domyślne są odrzucane. Implementujący FB
spełnia też kontrakty wszystkich przodków. Dozwolone są przypisania konkretnego FB
do interfejsu oraz interfejsu pochodnego do bazowego; kierunek odwrotny i konwersje
między rodzeństwem są odrzucane. Widoczność członków wynika z typu deklaracji.

`devices : ARRAY[1..3] OF I_Conveyor` tworzy osobne, początkowo puste sloty.
Przypisanie elementu kopiuje bieżące powiązanie, zachowując tożsamość FB.
Obsługujemy indeksowane metody, GET/SET, porównania elementów z dosłownym `0`
i `LOWER_BOUND`/`UPPER_BOUND`. Odbiorca wywołania jest wybierany raz, przed
argumentami lub prawą stroną SET. Sloty nie inicjalizują ponownie swoich celów
i nie przedłużają ich czasu życia. Inspekcja zwraca odłączone zagnieżdżone krotki
metadanych, bez uruchamiania getterów.

Tablice interfejsów są bezpośrednim magazynem w dozwolonych sekcjach `VAR`, GVL,
`VAR_TEMP` i `VAR_INST`; lokalne sloty mają czas życia danego wywołania.
Profil obejmuje 1–8 wymiarów z domkniętymi granicami DINT, maksymalnie 1000000
elementów. Każdy slot zajmuje jeden liść w limicie 1000000 liści; limit własnych
instancji FB pozostaje 10000. Poza profilem są inicjalizatory tablic, argumenty
konstruktorów na tablicy interfejsowej, operacje na całych tablicach, parametry
formalne tablic interfejsów w każdym trybie, aliasy, pola STRUCT, zagnieżdżone
`ARRAY OF ARRAY`, `REFERENCE TO` tablicy interfejsów i kowariancja tablic.
Bezpośrednie tablice wielowymiarowe są obsługiwane.

Python nie udostępnia ich przez `Cell`, `ArrayValue`, `check_value`, `default_value`
ani selektory własnych FB (`program_fb`, `global_fb`, `fb`). Wiązanie odbywa się
przez skalarne wejścia interfejsowe metod ST, np. `Bind(index, target)`.
Błędny uchwyt z innego Runtime powoduje `ArgumentError` przed zmianą stanu;
błędny indeks wykonawczy, null przy dereferencji i wygasły cel powodują fault.

`examples/conveyor_collections/` zawiera natywne XML `.TcIO`/`.TcPOU`/`.TcGVL`.
Menedżer `FB_Line` wiąże trzy różne FB w `FB_init`, przed pierwszym skanem, i steruje
nimi wyłącznie przez `I_Conveyor`. Standardowy przenośnik startuje po 100 ms,
odwracalny po 250 ms i raportuje ujemną prędkość, a trzeci po 500 ms; trzeci
zatrzaskuje alarm po 300 ms blokady. Usunięcie blokady wymaga `Reset` i `Start`.
`Bind` zachowuje stan nowego i poprzedniego celu; poprzedni przestaje otrzymywać
polecenia menedżera. Powiązanie `0` publikuje `FALSE`, `0.0`, `0`, `'Not bound'`.
Testy wykonują te pliki w emulatorze. Natywny format nie oznacza potwierdzonego
wykonania ani zgodności wykonawczej na TwinCAT; tego przykładu tam nie uruchamiano.

Uruchomienie z katalogu projektu:

```python
from pathlib import Path
import math
from tc_emulator import Runtime

source = Path("examples/conveyor_collections")
runtime = Runtime.from_files(sorted(source.glob("*.Tc*"), reverse=True))
line = runtime.program_fb("MAIN_Line", "line")
assert all(slot["valid"] for slot in line.inspect()["DEVICES"])
line.call_method("Start")
runtime.scan("MAIN_Line")
assert runtime.global_cell("GVL_Line", "running").value == (False, False, False)
runtime.advance_time(500)
runtime.scan("MAIN_Line")
speeds = runtime.global_cell("GVL_Line", "actualSpeed").value
assert all(math.isclose(a, b, abs_tol=1e-6) for a, b in zip(speeds, (0.5, -0.75, 0.6)))
replacement = runtime.instantiate("FB_StandardConveyor", init={"startDelay": 0})
replacement.set_property("SpeedSetpoint", 0.8)
replacement.call_method("Start")
line.call_method("Bind", index=2, target=replacement)
runtime.scan("MAIN_Line")
assert replacement.get_property("Running") is True
assert replacement.output("initCount") == 1
line.call_method("Bind", index=2, target=0)
runtime.scan("MAIN_Line")
assert runtime.global_cell("GVL_Line", "alarm").element(2).value == "Not bound"
line.call_method("Stop")
runtime.scan("MAIN_Line")
assert runtime.global_cell("GVL_Line", "running").value == (False, False, False)
```

## Dziedziczenie bloków funkcyjnych (v0.13)

`FUNCTION_BLOCK FB_MotorFake EXTENDS FB_MotorBase` dziedziczy pamięć,
metody, właściwości oraz zadeklarowane interfejsy bazy. Obsługujemy pojedyncze,
wielopoziomowe dziedziczenie własnych FB, niezależnie od kolejności deklaracji
lub plików. Każda instancja, również element tablicy, ma własną pamięć bazy,
zagnieżdżone FB i timery. `inspect()` pokazuje odziedziczony stan tylko raz.

Zwykłe wywołania, `THIS^` i wywołania przez interfejs wybierają najbardziej
pochodną implementację. Dotyczy to również wywołań z kodu bazy: jej metoda
może wywołać nadpisaną metodę `PROTECTED` potomka na tej samej instancji.
`PRIVATE` pozostaje dostępne tylko w leksykalnym zakresie deklarującego FB
oraz związane z jego implementacją. `PROTECTED` dopuszcza kod tego FB i jego
potomków; zewnętrzne ST i Python nie mogą go wywołać. Interfejsy wymagają
publicznych metod i akcesorów.

Ciało bazy nie wykonuje się automatycznie przy wywołaniu potomka.
`SUPER^()` jawnie wykonuje ciało bezpośredniej bazy deklarującego FB,
a `SUPER^.Method()` oraz odczyt/zapis `SUPER^.Property` wybierają implementację
widoczną w tej bazie. Wewnątrz tak wywołanego kodu zwykłe wywołania nadal
wybierają nadpisania potomka. `SUPER^.field` korzysta ze wspólnej pamięci
instancji; `SUPER` nie jest samodzielną wartością ani ogólnym wskaźnikiem.

Nadpisana metoda musi zachować nazwy, kolejność, kierunki i rozstrzygnięte typy
parametrów, typ wyniku, dostęp oraz kontrakt wartości domyślnych i wymaganych
argumentów. Nadpisanie właściwości zastępuje ją w całości: musi zachować typ,
dostęp oraz pełny zestaw akcesorów i ich dostęp. Nie łączymy brakującego GET
lub SET z implementacją bazy. Nazwy odziedziczonych zmiennych i członków nie
mogą być przesłaniane. Dotyczy to także nazw `VAR_TEMP`: ten profil odrzuca
wyjątek TwinCAT pozwalający potomkowi ponownie zadeklarować taką nazwę.
Sama zmienna `VAR_TEMP` jest widoczna wyłącznie w aktywacji ciała deklarującego
FB, bez dostępu z ciał potomków, metod lub akcesorów.

`VAR_INST` odziedziczonej metody należy do jej deklaracji i konkretnej instancji.
Nadpisanie oraz jawnie wywołana metoda bazy mają oddzielne banki tej pamięci.
W `inspect()["$VAR_INST"]` unikalna nazwa metody zachowuje krótki klucz, np. `M`.
Jeżeli baza i nadpisanie mają banki o tej samej nazwie metody, oba klucze są
kwalifikowane, np. `BASE.M` i `CHILD.M`, aby żaden stan nie został pominięty.
Dziedziczenie zachowuje dotychczasowe limity pamięci, budżety wykonania,
wirtualny czas, czas życia interfejsów i blokadę Runtime po błędzie.
Potencjalna rekurencja wywołań dynamicznych jest odrzucana konserwatywnie.

**Przykład trzech przenośników:** `examples/conveyor_inheritance/` zawiera
natywne `.TcPOU`, `.TcGVL` i `.TcIO`. `FB_MotorBase IMPLEMENTS I_Motor`
przechowuje wspólny stan, właściwości i timer startu w metodzie `Update`.
`FB_MotorSim` dziedziczy tę implementację; `FB_MotorFake` nadpisuje chroniony
`CheckFault`, wywołując też `SUPER^.CheckFault()`. Odziedziczone `Update`
i `Faulted` korzystają z tego nadpisania. Ciała obu potomków demonstrują
jawne `SUPER^()`. Sterowniki nadal sterują silnikami przez `I_Motor`.

Uruchomienie z katalogu projektu:

```python
from pathlib import Path
from tc_emulator import Runtime

source = Path("examples/conveyor_inheritance")
runtime = Runtime.from_files(sorted(source.glob("*.Tc*")))
runtime.scan("MAIN_Line")
fake = runtime.instantiate("FB_MotorFake")
fake.set_property("SpeedSetpoint", 2.0)  # Setter odziedziczony z bazy.
assert fake.get_property("SpeedSetpoint") == 1.0
second = runtime.program_fb("MAIN_Line", "conveyors", 2)
second.call_method("BindMotor", motor=fake)  # Odziedziczony I_Motor.
second.set_property("SpeedSetpoint", 0.75)
runtime.global_cell("GVL_Line", "start").value = [True, True, True]
runtime.scan("MAIN_Line")
runtime.global_cell("GVL_Line", "start").value = [False, False, False]
runtime.advance_time(500)  # Trzy niezależne opóźnienia: 100/250/500 ms.
runtime.scan("MAIN_Line")
assert runtime.global_cell("GVL_Line", "running").value == (True, True, True)
assert fake.get_property("ActualSpeed") == 0.75  # Właściwość bazy.

fake.set_input("fault", True)
runtime.scan("MAIN_Line")
assert runtime.global_cell("GVL_Line", "running").value == (True, False, True)
assert second.get_property("Alarm") == "Motor fault"
fake.set_input("fault", False)
runtime.scan("MAIN_Line")
assert second.get_property("Running") is False
second.call_method("Start", delay=250)  # Usunięcie awarii wymaga nowego startu.
runtime.scan("MAIN_Line")
runtime.advance_time(250)
runtime.scan("MAIN_Line")
assert runtime.global_cell("GVL_Line", "running").value == (True, True, True)
```

`examples/test_conveyor_inheritance.py` sprawdza niezależne opóźnienia,
dynamiczny hook, podmianę drugiego silnika, izolację awarii i restart,
`SUPER`, odziedziczone właściwości, ograniczenia dostępu oraz liczniki produktów.
Przykłady z poprzednich wersji pozostają dostępne.

Poza zakresem pozostają `ABSTRACT`, `FINAL`, `INTERNAL`, dziedziczenie
wbudowanych FB i interfejsów, ogólne operatory wskaźnikowe,
`FB_exit`/`FB_reinit`, akcje SFC, online change i semantyka trwałości PLC.
Nieobsługiwane deklaracje są odrzucane. Dziedziczenie nie dodaje kopiowania FB
przez wartość ani przekazywania FB przez `VAR_IN_OUT`.

## Referencje do danych i wspólna konfiguracja (v0.14)

`REFERENCE TO T` wiąże nazwę z istniejącą, zapisywalną pamięcią danych.
`r REF= x` zmienia powiązanie, a zwykłe `r := wartość` zapisuje do celu.
`dest := r` odczytuje wartość celu; `r1 := r2` kopiuje wartości.
`r1 REF= r2` przejmuje bieżący cel `r2`: późniejsze przepięcie `r2` nie przepina `r1`.
Pola struktur i elementy tablic także mogą być celami referencji. Typ celu musi
pasować dokładnie, po rozwiązaniu aliasów; wiązanie nie poszerza liczb, nie zmienia
pojemności STRING ani granic tablic i zachowuje nominalną zgodność typów UDT.

Nowa referencja jest pusta. `r REF= 0` odłącza cel, a kopiowanie pustej referencji
przez `REF=` daje pustą referencję. Odczyt lub zapis pustego celu powoduje
`ExecutionError`. `__ISVALIDREF(r)` zwraca FALSE dla pustej lub
wygasłej referencji. Referencja nie przedłuża życia danych: lokalne dane wywołania
i `VAR_TEMP` wygasają po zakończeniu swojej aktywacji. Odczyt, zapis oraz próba
przejęcia wygasłego celu powodują `ExecutionError`; wyczyszczenie przez `REF= 0`
pozostaje dozwolone. Dane PROGRAM/GVL/FB/VAR_INST i komórki utworzone w Pythonie
żyją wraz z właścicielem. Kontrola wygaśnięcia w `__ISVALIDREF` jest rozszerzeniem
emulatora względem natywnego testu niezerowej referencji w TwinCAT. Przykład nie
stanowi deklaracji pełnej zgodności z TwinCAT.

Oba zapisy inicjalizacji, `r : REFERENCE TO T := target` oraz
`r : REFERENCE TO T REF= target`, wiążą referencję. Cel inicjalizatora musi być
bezpośrednim adresem zwykłych zapisywalnych danych; indeksy muszą być stałymi
wyrażeniami. Łańcuchy przez inną referencję są zabronione. Zwykła pamięć jest
alokowana i inicjalizowana przed wiązaniem, więc można wskazać dane zadeklarowane
później. Trwały inicjalizator nie może wskazywać danych lokalnych wywołania,
`VAR_TEMP` ani `VAR_IN_OUT`. Inicjalizator `VAR_INST` może wskazać własne
`VAR_INST` metody lub trwałe pola właściciela. Inicjalizatory tymczasowe wykonują
się po przygotowaniu argumentów i lokalnej pamięci. Trwałe wiązania nie są
ponawiane przy każdym skanie.

W `VAR_INPUT` typu referencyjnego argument ST `config := GVL_Line.config` wiąże
pamięć zamiast kopiować strukturę. Pominięcie takiego wejścia FB zachowuje jego
powiązanie. Funkcje i metody wymagają argumentu, chyba że wejście ma pustą wartość
domyślną. Dla funkcji, metod i prototypów metod interfejsu dozwolona jest
wyłącznie jawna pusta wartość domyślna; niezerowe wartości są odrzucane.
Wejście referencyjne FB może mieć inicjalizator wskazujący bezpośrednio zwykłą
pamięć, a pominięcie argumentu zachowuje powiązanie. Z Pythona przekaż do
`set_input("config", cell)` zapisywalną, żywą
`Cell` z tego samego Runtime i o dokładnie zgodnym typie, albo całkowite `0`,
aby odłączyć cel. Zwykły słownik, wartość BOOL, obca komórka, widok bitowy i
wygasła komórka są odrzucane. Tę samą zasadę obsługują `Runtime.call`,
`FBHandle.call` i `call_method` dla wejść referencyjnych. `global_cell`,
`program_cell`, `runtime.cell`, `Cell.field()` i `Cell.element()` udostępniają
pamięć wartości; nie udostępniają surowego slotu referencji. Migawka `inspect()`
opisuje referencję przez typ celu i ważność, bez adresów i żywych obiektów Cell.

`AND_THEN` i `OR_ELSE` działają tylko dla BOOL i skracają obliczanie: FALSE po
lewej stronie `AND_THEN` oraz TRUE po lewej stronie `OR_ELSE` pomijają prawy
operand. Pozwala to bezpiecznie zapisać
`__ISVALIDREF(config) AND_THEN config.enabled`. Zwykłe `AND` i `OR` pozostają
zachłanne. Walidacja sprawdza oba operandy także wtedy, gdy jeden zostanie pominięty;
pominięte wywołanie nie wykonuje skutków ubocznych.

Obsługiwane cele to istniejące typy wartości: skalarne, STRING, ENUM, STRUCT
i tablice o stałych granicach, również przez aliasy. Referencje można deklarować
w `VAR`, `VAR_TEMP`, `VAR_INST`, `VAR_GLOBAL` i `VAR_INPUT`, także w lokalnych
deklaracjach funkcji, metod i akcesorów. Wejścia referencyjne metod interfejsu
wymagają identycznych kontraktów implementacji i przesłonięć. Zakres v0.14 nie
obejmuje `POINTER TO`/`ADR`, referencji do FB, interfejsów ani otwartych tablic,
referencji zwracanych z funkcji/metod i właściwości, zagnieżdżonych referencji,
struktur/tablic zawierających referencje ani aliasów wskazujących typ referencyjny.
Nie można deklarować referencji w `VAR_OUTPUT`, `VAR_IN_OUT` i `CONSTANT`.
Stałe, wyniki właściwości, wartości tymczasowe i widoki bitowe nie są celami wiązania.
Żywy cel referencji może natomiast zostać przekazany do zwykłego `VAR_IN_OUT`,
także do otwartej tablicy.

### Trzy przenośniki korzystające z jednej struktury

Natywne pliki w `examples/conveyor_references/` deklarują jedną zwykłą strukturę
`ST_ConveyorConfig` w GVL: `enabled := TRUE`, `speed := 0.75`,
`startDelay := T#100ms`. Każdy z trzech FB posiada własny TON i własne wyjścia,
a ich wejścia `config` wskazują tę samą strukturę. PROGRAM wiąże wejścia podczas
pierwszego skanu i zachowuje ich powiązania w kolejnych skanach.

Uruchom poniższy scenariusz z katalogu głównego repozytorium po instalacji pakietu
(np. `python -m pip install -e .`). Czas jest wirtualny: `advance_time` przesuwa
zegar, a `scan` dopiero aktualizuje wyjścia.

```python
from pathlib import Path
from tc_emulator import Runtime

rt = Runtime.from_files(sorted(Path("examples/conveyor_references").glob("*.Tc*")))
config = rt.global_cell("GVL_Line", "config")
running = rt.global_cell("GVL_Line", "running")
speed = rt.global_cell("GVL_Line", "actualSpeed")
missing = rt.global_cell("GVL_Line", "missingConfig")

rt.scan("MAIN_Line")
assert running.value == (False, False, False)
rt.advance_time(99)
rt.scan("MAIN_Line")
assert running.value == (False, False, False)
rt.advance_time(1)
rt.scan("MAIN_Line")
assert running.value == (True, True, True)
assert speed.value == (0.75, 0.75, 0.75)

config.field("speed").value = 0.4
rt.scan("MAIN_Line")
assert speed.value == (0.4, 0.4, 0.4)
config.field("enabled").value = False
rt.scan("MAIN_Line")
assert running.value == (False, False, False)
assert speed.value == (0.0, 0.0, 0.0)
config.field("enabled").value = True
rt.scan("MAIN_Line")
rt.advance_time(100)
rt.scan("MAIN_Line")
assert running.value == (True, True, True)

second = rt.program_fb("MAIN_Line", "conveyors", 2)
second.set_input("config", 0)
rt.scan("MAIN_Line")
assert running.value == (True, False, True)
assert speed.value == (0.4, 0.0, 0.4)
assert missing.value == (False, True, False)
assert second.output("alarm") == "Missing configuration"
rt.advance_time(1000)
rt.scan("MAIN_Line")
assert running.value == (True, False, True)

second.set_input("config", config)
rt.scan("MAIN_Line")
assert missing.value == (False, False, False)
assert running.value == (True, False, True)
rt.advance_time(99)
rt.scan("MAIN_Line")
assert running.value == (True, False, True)
rt.advance_time(1)
rt.scan("MAIN_Line")
assert running.value == (True, True, True)
assert speed.value == (0.4, 0.4, 0.4)
assert second.output("alarm") == ""
```

Automatyczne testy scenariusza: `python -m pytest examples/test_conveyor_references.py`.

## Inicjalizacja bloków funkcyjnych (v0.15)

Nowa instancja FB wykonuje inicjalizację przed pierwszym zwykłym wywołaniem.
Dotyczy to także FB w PROGRAM, GVL, zagnieżdżonych FB i elementów tablic.
`Runtime.from_files` oraz `from_source` zwracają Runtime z przygotowanymi
instancjami trwałymi, a `instantiate` zwraca gotową nową instancję.
Kolejne skany i wywołania nie powtarzają tej inicjalizacji.

`METHOD PUBLIC FB_init : BOOL` ma dwa obowiązkowe pierwsze wejścia
`bInitRetains : BOOL` i `bInCopyCode : BOOL`, bez wartości domyślnych.
Runtime dostarcza odpowiednio `TRUE` i `FALSE`. Dalsze parametry to `VAR_INPUT`;
mogą mieć zwykłe wartości domyślne oraz typy wartościowe, referencyjne lub
interfejsowe zgodne z dotychczasowym zakresem. Wynik `BOOL`, także `FALSE`,
jest ignorowany. `VAR_OUTPUT` i `VAR_IN_OUT` tego konstruktora są odrzucane.
Nie można jawnie wywołać `FB_init` ze ST ani Pythona, także przez `SUPER^`.

Parametry deklaracji i przypisania po inicjalizacji są osobnymi etapami:

```iecst
motor : FB_Motor(axisId := 1) := (enable := TRUE, SpeedSetpoint := 0.5);
motors : ARRAY[1..2] OF FB_Motor[(axisId := 1), (axisId := 2)]
    := [(enable := TRUE), (enable := FALSE)];
```

`FB_Motor` w tym zapisie oznacza własny FB z odpowiednim `FB_init`, wejściem
`enable` i zapisywalną właściwością `SpeedSetpoint`. Argumenty konstruktora
mogą być nazwane albo pozycyjne; nie można mieszać form, powtarzać nazw ani
podawać flag systemowych. Dla tablic argumenty wspólne zapisuje się za typem,
np. `ARRAY[1..2] OF FB_Motor(axisId := 1)`, a osobne w płaskiej liście jak wyżej.
Jawna lista parametrów musi zawierać dokładnie jeden zestaw na każdy element,
w kolejności deklaracji; w tablicach wielowymiarowych ostatni indeks zmienia
się najszybciej. Wspólne argumenty nie współdzielą pamięci samych instancji.

Po konstruktorach wykonywane są przypisania do istniejących publicznych
`VAR_INPUT` oraz właściwości z publicznym setterem. Referencje i interfejsy
wiążą tożsamość celu. Wpisy wykonują się w kolejności źródła; prawa strona
każdego wpisu jest obliczana bezpośrednio przed przypisaniem. Obsługiwane są
wyrażenia stałe i bezpośrednie wartości lub referencje do pamięci w leksykalnym
zakresie deklaracji. Wywołania ze skutkami ubocznymi i odczyty właściwości
w wyrażeniach deklaracji są odrzucane. Nie można inicjalizować w ten sposób
prywatnych pól ani wyjść. Wartości i wiązania trwałej instancji nie mogą
przechwytywać danych lokalnych wywołania ani `VAR_IN_OUT`.

Pełna pamięć PROGRAM/GVL jest alokowana przed rozpoczęciem metod startowych.
Przed nimi wiązane są deklarowane referencje w całym trwałym drzewie pamięci;
pozwala to konstruktorowi korzystać z referencji do danych zadeklarowanych
później. Dzieci inicjalizują się przed właścicielem, w kolejności deklaracji.
Dla jednej instancji kolejność jest następująca:

1. Przygotowanie pamięci i wiązań referencyjnych.
2. Własne implementacje `FB_init` kolejnych klas, od najstarszej bazy do potomka.
3. Przypisania wejść i właściwości z deklaracji instancji.
4. Efektywne metody oznaczone `call_after_init`, po jednej na nazwę.

Potomny `FB_init` zachowuje cały prefiks parametrów bazy: nazwy, kierunki,
rozstrzygnięte typy i wartości domyślne; może dodać dalsze wejścia. Jeżeli go
nie deklaruje, odziedziczona inicjalizacja nadal się wykonuje. Łańcuch
konstruktorów jest automatyczny. Zwykłe wywołania metod z ich ciał nadal
korzystają z dynamicznego wyboru implementacji.

`{attribute 'call_after_init'}` zapisuje się bezpośrednio przed deklaracją
`FUNCTION_BLOCK` oraz przed wybraną `METHOD`. Oznaczona metoda wymaga oznaczonego
FB; potomkowie oznaczonego FB również wymagają tego atrybutu. Hook nie ma
parametrów formalnych, ale może mieć lokalne `VAR`/`VAR_INST` i wynik, który
jest ignorowany. Nadpisanie zachowuje atrybut i zastępuje hook bazy. Jeżeli
ma wykonać także kod bazy, wywołuje jawnie `SUPER^.NazwaHooka()`.
Różne nazwy hooków wykonują się według deklaracji od bazy do potomka — to jawna
reguła profilu emulatora. Atrybut nie jest dozwolony na metodach cyklu życia.

Lokalne instancje funkcji/metody inicjalizują się raz na aktywację, po związaniu
jej wejść; `VAR_TEMP` przy każdym wywołaniu ciała, a `VAR_INST` raz na właściciela.
Inicjalizacja korzysta ze wspólnego budżetu kroków, głębokości i zegara danego
wywołania; start całego Runtime ma jeden wspólny budżet. Błąd ST w konstruktorze,
setterze lub hooku daje `ExecutionError` ze źródłem; istniejący Runtime zostaje
zablokowany zgodnie z dotychczasową obsługą błędów. Nie ma wycofywania zmian.

### Trzy przenośniki gotowe przed pierwszym skanem

`examples/conveyor_initialization/` jest samodzielnym zestawem `.TcPOU`,
`.TcGVL` i `.TcDUT`. `FB_ConveyorBase` wiąże wspólną konfigurację i zapisuje ID;
`FB_Conveyor` dodaje własny `FB_init`. Deklaracja tablicy przekazuje osobne ID
1/2/3, a po konstruktorach ustawia `StartDelay` na 100/250/500 ms i właściwość
`SpeedFactor` na 1.0. Nadpisany hook wywołuje bazę przez `SUPER^.AfterInit()`.
PROGRAM tylko wywołuje przenośniki i publikuje wyjścia — nie wymaga flagi
pierwszego skanu ani ręcznego wiązania konfiguracji.

Przed skanem każda instancja ma `ready = TRUE`, `baseInitCount = 1`,
`derivedInitCount = 1`, `afterInitCount = 1` i `initTrace = 12345`.
Cyfry śladu oznaczają kolejno konstruktor bazy, konstruktor potomka,
setter, hook bazy i hook potomka. Jest to instrumentacja tego przykładu,
nie publiczny mechanizm zdarzeń cyklu życia. Ponowne ręczne wywołanie settera
również dopisze cyfrę do śladu.

Uruchom z katalogu projektu po instalacji pakietu:

```python
from pathlib import Path
from tc_emulator import Runtime

rt = Runtime.from_files(sorted(Path("examples/conveyor_initialization").glob("*.Tc*")))
second = rt.program_fb("MAIN_Line", "conveyors", 2)
assert second.output("ready") is True
assert second.output("initTrace") == 12345
assert second.output("id") == 2
assert second.inspect()["STARTDELAY"] == 250

rt.scan("MAIN_Line")
running = rt.global_cell("GVL_Line", "running")
assert running.value == (False, False, False)
rt.advance_time(100)
rt.scan("MAIN_Line")
assert running.value == (True, False, False)
rt.advance_time(150)
rt.scan("MAIN_Line")
assert running.value == (True, True, False)
rt.advance_time(250)
rt.scan("MAIN_Line")
assert running.value == (True, True, True)

config = rt.global_cell("GVL_Line", "config")
config.field("speed").value = 0.4
rt.scan("MAIN_Line")
assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.4, 0.4, 0.4)
config.field("enabled").value = False
rt.scan("MAIN_Line")
assert running.value == (False, False, False)
config.field("enabled").value = True
rt.scan("MAIN_Line")  # Nowy początek odmierzania każdego opóźnienia.
rt.advance_time(500)
rt.scan("MAIN_Line")
assert running.value == (True, True, True)
assert second.output("initTrace") == 12345
```

### Parametry inicjalizacji z Pythona

`Runtime.instantiate(name, *, init=None, inputs=None)` przyjmuje dwa mapowania.
`init` przekazuje dodatkowe wejścia `FB_init`, a `inputs` wejścia i właściwości
ustawiane po nim. Nazwy nie rozróżniają wielkości liter, a kolejność przypisań
odpowiada kolejności wpisów w mapowaniu Pythona. Wszystkie argumenty obu mapowań
są sprawdzane przed wykonaniem ST. Błędna nazwa, brak wymaganego parametru,
duplikat różniący się wielkością liter, niezgodny typ lub obcy uchwyt/Cell daje
`ArgumentError` bez skutków ubocznych kodu użytkownika i bez blokowania Runtime.
`instantiate(name)` działa nadal, jeśli konstruktor nie wymaga argumentów.

Kontynuując poprzedni przykład, można utworzyć niezależne instancje korzystające
z tej samej `Cell`, również z komórki utworzonej przez `rt.cell`:

```python
shared = rt.cell("ST_ConveyorConfig", {"enabled": True, "speed": 0.6})
standalone = rt.instantiate(
    "FB_Conveyor",
    init={"conveyorId": 10, "sharedConfig": shared, "defaultDelay": 900},
    inputs={"StartDelay": 100, "SpeedFactor": 1.0},
)
assert standalone.output("ready") is True
assert standalone.output("initTrace") == 12345
standalone.call()
rt.advance_time(100)
standalone.call()
assert standalone.output("actualSpeed") == 0.6
shared.field("speed").value = 0.2
standalone.call()
assert standalone.output("actualSpeed") == 0.2
```

`TIME` w API Pythona oznacza całkowite milisekundy. Referencje wymagają żywej,
zapisywalnej komórki zgodnego typu z tego samego Runtime albo całkowitego `0`;
interfejsy wymagają zgodnego uchwytu FB z tego Runtime albo `0`. Obowiązują
dotychczasowe zasady czasu życia danych. Deklaracje inicjalizacji nie tworzą
harmonogramu zależności między instancjami; nie należy zakładać gotowości
innej instancji tylko dlatego, że jej pamięć została już przydzielona.

Testy `examples/test_conveyor_initialization.py` sprawdzają gotowość przed
skanem, kolejność i liczniki, osobne timery, żywą wspólną konfigurację,
restart po wyłączeniu i brak ponownej inicjalizacji podczas zwykłej pracy.
Pliki przykładu są także fixture kolejności w formacie natywnym do przyszłego
porównania z TwinCAT. Nie wykonano ich na natywnym TwinCAT; testy emulatora
nie potwierdzają zgodności kolejności z runtime Beckhoff.

Profil v0.15 dotyczy wyłącznie nowych instancji. Nie obejmuje restartu PLC,
`RETAIN`/`PERSISTENT`, online change, kopiowania instancji, `FB_exit` ani
`FB_reinit`. Nieznane atrybuty i konstrukcje są nadal odrzucane, także w kodzie,
który nie zostanie wywołany. Wcześniejsze przykłady pozostają dostępne.

## Akcje ST i atrybuty enumów (v0.16)

Akcja należy do FB albo PROGRAM i wykonuje wyłącznie wybrane ciało na pamięci
właściciela. Nie wywołuje jego głównego ciała ani `FB_init`. W samodzielnym ST
zapisz `ACTION Nazwa: ... END_ACTION` po głównym ciele właściciela, obok jego
metod/właściwości. Pełny przykład z dwiema akcjami i enumem:

```python
from tc_emulator import Runtime

rt = Runtime.from_source("""
{attribute 'strict'}
{attribute 'qualified_only'}
TYPE E_State : (Stopped := 0, Running := 2); END_TYPE
FUNCTION_BLOCK Motor
VAR_INPUT enable : BOOL := TRUE; END_VAR
VAR_OUTPUT state : E_State := E_State.Stopped; calls : DINT; END_VAR
Step();
ACTION Step:
    IF enable THEN state := E_State.Running;
    ELSE state := E_State.Stopped; END_IF;
    calls := calls + 1;
END_ACTION
ACTION Stop: state := E_State.Stopped; END_ACTION
END_FUNCTION_BLOCK
""")
motor = rt.instantiate("Motor")
assert motor.call_action("Step", enable=True) is None
assert motor.output("state").name == "RUNNING"
assert motor.output("calls") == 1
motor.call_action("Stop")
assert motor.output("state").name == "STOPPED"
assert motor.output("calls") == 1
```

Wywołania ST obejmują `Step()`, `THIS^.Step()`, `fb.Step()`,
`items[i].Step()`, `MAIN.Step()` oraz `SUPER^.Step()`. Akcje FB są dziedziczone
z dynamicznym wyborem nadpisania, także przy wywołaniu z ciała bazy;
`SUPER^` wybiera implementację leksykalnej bazy. PROGRAM nie ma dziedziczenia;
`THIS^`/`SUPER^` są ograniczone do FB. FUNCTION nie może wywołać akcji PROGRAM.
Natywny `.TcPOU` przechowuje ciało w
`<Action Name="Step" Id="{GUID}"><Implementation><ST>...</ST></Implementation></Action>`.
Sekcja ST zawiera same instrukcje, bez `ACTION`/`END_ACTION` i bez Declaration.

Akcje nie mają własnych parametrów, zmiennych lokalnych ani wyniku i nie mogą
być wyrażeniami lub metodami interfejsu. Argumenty nazwane i mapowania `=>`
korzystają z wejść/wyjść właściciela. Zewnętrzne wywołanie wymaga wszystkich jego
`VAR_IN_OUT`; lokalne używa bieżących wiązań. Pominięte wejścia zachowują wartość.
Kontrakt zewnętrznego wywołania ST pochodzi ze statycznego typu odbiorcy,
a Pythona z konkretnego typu uchwytu; lokalne/THIS/SUPER używają zakresu
leksykalnego. Akcje współdzielą aktywację `VAR_TEMP` właściciela z jego bieżącym
ciałem i zagnieżdżonymi akcjami; zewnętrzne wywołanie tworzy świeżą aktywację.
Nie widzą zmiennych lokalnych wywołującej metody. `RETURN` kończy tylko akcję.
Obowiązują wspólne limity wykonania, wykrywanie cykli i blokada po błędzie.
Nie obejmuje to SFC ani kwalifikatorów akcji SFC.

Oba atrybuty enumów umieszcza się bezpośrednio przed `TYPE`, w dowolnej kolejności.
W bloku z wieloma deklaracjami dotyczą tylko pierwszej. Duplikaty, wartości
atrybutów, inne położenia i atrybuty na typach niebędących enumem są odrzucane.
`qualified_only` wymaga `E_State.Running` poza domyślną wartością deklarowanego
enumu. `strict` zachowuje tożsamość typu: odrzuca arytmetykę, przypisania z innych
enumów i zmiennych całkowitych. Pozwala przypisać stałe wyrażenie całkowite tylko
wtedy, gdy jego wartość odpowiada zadeklarowanemu członkowi; wynik jest wartością
enumu. Dotyczy to również inicjalizatorów i wejść wartościowych. `VAR_IN_OUT`
i mapowania wyjściowe wymagają dokładnego typu enumu. Enumy bez `strict` zachowują
wcześniejsze reguły nominalne. Python nadal przyjmuje nazwę członka lub `EnumValue`,
a odrzuca surowe liczby i bool; atrybut nie dodaje ogólnej konwersji w runtime.

### Trzy przenośniki: start, zablokowanie, reset i ponowny start

`examples/conveyor_actions/` zawiera sześć ręcznie napisanych plików w natywnym
formacie `.TcPOU`/`.TcDUT`/`.TcGVL`. Nie są eksportem z IDE i nie wykonano ich
na TwinCAT. Testy uruchamiają je w tc-emulator; nie dowodzą zgodności z Beckhoff.
Wspólna GVL przechowuje wejścia `start`, `blocked`, `reset`, konfigurację i wyjścia.
Każdy FB ma osobne timery startu i zablokowania. Bazowe akcje sterują stanem
`Stopped`/`Starting`/`Running`/`Fault`; nadpisana akcja `UpdateOutputs` wywołuje
`SUPER^.UpdateOutputs()` i wyznacza alarm. PROGRAM wykonuje kolejno
`ReadInputs`, `ControlConveyors`, `WriteOutputs`. Z katalogu repozytorium:

```python
from pathlib import Path
from tc_emulator import Runtime

rt = Runtime.from_files(sorted(Path("examples/conveyor_actions").glob("*.Tc*")))
for index in range(1, 4):
    rt.global_cell("GVL_Line", "start").element(index).value = True
rt.call_action("MAIN_Line", "ReadInputs")
rt.call_action("MAIN_Line", "ControlConveyors")
rt.call_action("MAIN_Line", "WriteOutputs")  # t=0: wszystkie Starting
running = rt.global_cell("GVL_Line", "running")
assert running.value == (False, False, False)
for elapsed, expected in (
    (100, (True, False, False)),
    (150, (True, True, False)),
    (250, (True, True, True)),
):
    rt.advance_time(elapsed)
    rt.scan("MAIN_Line")
    assert running.value == expected

rt.global_cell("GVL_Line", "blocked").element(2).value = True
rt.scan("MAIN_Line")  # t=500: początek blokady drugiego przenośnika
rt.advance_time(300)
rt.scan("MAIN_Line")  # t=800: tylko drugi Fault
second = rt.program_fb("MAIN_Line", "conveyors", 2)
assert second.output("state").name == "FAULT"
assert running.value == (True, False, True)
rt.global_cell("GVL_Line", "blocked").element(2).value = False
rt.scan("MAIN_Line")
assert second.output("alarm") is True  # Usunięcie przeszkody nie kasuje alarmu.
rt.global_cell("GVL_Line", "start").element(2).value = False
rt.global_cell("GVL_Line", "reset").element(2).value = True
rt.scan("MAIN_Line")
assert second.output("state").name == "STOPPED"
rt.global_cell("GVL_Line", "reset").element(2).value = False
rt.global_cell("GVL_Line", "start").element(2).value = True
rt.scan("MAIN_Line")
rt.advance_time(250)
rt.scan("MAIN_Line")  # t=1050: drugi znowu Running
assert running.value == (True, True, True)
assert second.output("alarm") is False
second.call_action("UpdateOutputs")  # Tylko wyjścia, bez ponownego sterowania.
for index in range(1, 4):
    fb = rt.program_fb("MAIN_Line", "conveyors", index)
    assert fb.output("initTrace") == 12345
    assert fb.output("baseInitCount") == fb.output("derivedInitCount") == 1
    assert fb.output("afterInitCount") == 1
```

Wejście w `Starting` następuje w pierwszym skanie z `start = TRUE`; opóźnienia
wynoszą 100/250/500 ms od tego skanu. Ciągła blokada w Starting albo Running
przez 300 ms daje Fault w skanie osiągającym termin; przerwanie blokady zeruje
ten timer. Reset podczas blokady jest ignorowany; poprawny reset daje Stopped,
a następny skan z żądaniem startu rozpoczyna nowe pełne opóźnienie. Stan Fault
pozostaje zatrzaśnięty także po wyłączeniu startu/konfiguracji. Czas jest jawny:
`advance_time` nie skanuje kodu. Liczniki `FB_init` pozostają równe jeden.
Testy: `.venv/bin/python -m pytest examples/test_conveyor_actions.py -q`.
Ograniczenia cyklu życia z v0.15, w tym brak restartu PLC/online change, pozostają.

## Arytmetyka: profil checked-subset

- BYTE ma 8 bitów, INT/UINT/WORD 16, DINT/UDINT/DWORD 32; przepełnienie przy zapisie daje błąd.
- Całkowite wyniki pośrednie są sprawdzane w zakresie signed 64-bit. Nie ma zawijania liczb.
- BOOL jest odrębny od int; Pythonowe `True` nie może zastąpić wartości INT.
- Dla liczb rzeczywistych wspólny typ wybieramy według LREAL > REAL > INTEGER,
  konwertujemy oba operandy przed operacją lub porównaniem i zaokrąglamy wynik
  do tego typu (REAL po każdej operacji do binary32). To deterministyczna reguła
  emulatora, nie gwarancja zgodności z każdym docelowym procesorem TwinCAT.
- Całkowite można przypisać do REAL/LREAL; nie ma niejawnego przypisania float do int.
  MOD nadal działa wyłącznie na liczbach całkowitych.
- `/` z operandem REAL/LREAL dzieli zmiennoprzecinkowo. NaN/Infinity/przepełnienia
  i dzielenie przez zero są błędami; wartości subnormalne i zaokrąglenie do zera są dozwolone.
- Dzielenie całkowite zaokrągla w stronę zera: `-7 / 3 = -2`, `-7 MOD 3 = -1`.
- AND/OR obliczają oba operandy. Argumenty i operandy wykonują się od lewej do prawej.
- FOR oblicza granice i krok na wejściu, obejmuje wartość końcową i odrzuca BY=0.
  Końcowe zwiększenie licznika też podlega kontroli zakresu jego typu.

To jawne reguły tego runtime'u. [TwinCAT uzależnia część zachowania arytmetyki
od platformy docelowej](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528853899.html).
Zgodność wszystkich konwersji, przepełnień i efektów ubocznych z TwinCAT nie jest
zweryfikowana. Nie używaj tego profilu jako referencji dla testów zawijania liczb.

## Błędy i limity

`ParseError` i `ValidationError` wykrywają błędy źródeł. `ArgumentError` oznacza
błędne użycie API; wszystkie argumenty są sprawdzane przed zmianą stanu instancji.
Błąd wykonania daje `ExecutionError`, miejsce w ST i stos wywołań. Dla `.TcPOU`
i `.TcDUT` numery linii odnoszą się do wskazanej sekcji Declaration lub Implementation.

Domyślny budżet to 100 000 kroków i 128 ramek wywołań. Można go ustawić przez
`Runtime.from_source(..., max_steps=..., max_call_depth=...)` lub `from_files`.
Budżet jest wspólny dla całego wywołania z Pythona, obejmuje puste pętle i wywołania
zagnieżdżone. Rekurencyjne cykle wywołań i definicji FB są odrzucane podczas walidacji.
Limity służą testom i nie stanowią izolacji nieufnego kodu.

Po błędzie wykonania część stanu może być zmieniona. Odczyt i inspekcja pozostają
możliwe, lecz kolejne wykonanie lub zmiana stanu dają `RuntimeFaultedError`.
Utwórz nowy Runtime dla następnego testu; nie ma automatycznego rollbacku.
Jeden Runtime jest przeznaczony do wywołań sekwencyjnych.

## Testy i rozwój

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest examples -q
ruff check .
ruff format --check .
```

Przykłady i testy wykonują rzeczywisty kod ST. Zakres sprawdzono na Linuxie;
nie wykonano jeszcze testów porównawczych na zainstalowanym TwinCAT ani testów na Windows.

Projekt i plan implementacji znajdują się w `docs/superpowers/`.
