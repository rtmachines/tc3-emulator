# Runtime ST w Pythonie — projekt pierwszej wersji

Status: zakres zaakceptowany przez użytkownika 2026-10-27. Dokument opisuje kontrakt v0.1; instrukcja użycia znajduje się w README.md.

## Cel i ustalenia użytkownika

Zbudować narzędzie do szybkiego testowania funkcji i bloków funkcyjnych napisanych
w Structured Text. Ma działać bez zainstalowanego TwinCAT, również na Linuxie.
Użytkownik zaproponował runtime interpretujący ST w Pythonie zamiast kompilatora.
Przyjmujemy tę sugestię jako kierunek niniejszej propozycji.

Sukces pierwszej wersji oznacza możliwość wczytania źródeł ST, wywołania funkcji,
utworzenia niezależnych instancji FB i sprawdzenia ich wyników w testach Pythona.
Nie deklarujemy pełnej zgodności z językiem, bibliotekami ani runtime TwinCAT.

## Rozważone podejścia

1. **Interpreter napisany w Pythonie — proponowany kierunek po sugestii użytkownika.**
   ST jest parsowany raz, sprawdzany i wykonywany przez własny interpreter.
   Ułatwia integrację z pytest, inspekcję stanu i rozwijanie semantyki.
   Koszt: własna implementacja języka i mniejsza wydajność niż wykonanie natywne.
2. **Interpreter napisany w Rust.** Podobna architektura i podobny koszt odtworzenia
   semantyki, z możliwością dostarczenia samodzielnego programu. Wcześniejsza
   propozycja asystenta; użytkownik wskazał Python jako alternatywę.
3. **Runner wykorzystujący RuSTy.** Gotowy kompilator ST zmniejsza zakres własnej
   implementacji języka, ale dodaje LLVM, linker i integrację kodu natywnego.
   Zgodność z konkretnymi źródłami TwinCAT nadal wymaga sprawdzenia.

Nie tłumaczymy ST na kod uruchamiany przez Pythonowe eval/exec. Własny interpreter
wykonuje instrukcje ST i stosuje jawne reguły typów PLC. AST, czyli drzewo
rozpoznanych instrukcji, jest wewnętrzną reprezentacją źródła, nie kodem maszynowym.

## Proponowany zakres v0.1

Poniższe ograniczenia są decyzjami asystenta do zatwierdzenia, a nie dodatkowymi
wymaganiami zadeklarowanymi przez użytkownika.

- Biblioteka Python 3.11+; główny scenariusz to testy pisane w Pythonie/pytest.
  Runtime nie zależy od pytest. Brak GUI i osobnego języka scenariuszy testowych.
- Samodzielne pliki `.st`, także z kilkoma deklaracjami FUNCTION/FUNCTION_BLOCK,
  oraz prosty import `.TcPOU` zawierającego deklarację i implementację ST.
- `FUNCTION`, `FUNCTION_BLOCK`, `VAR_INPUT`, `VAR_OUTPUT`, `VAR`, `VAR_TEMP`
  w FB i `VAR_IN_OUT`. FUNCTION może mieć wynik i dodatkowe VAR_OUTPUT.
- Typy `BOOL`, `INT`, `UINT`, `DINT`, `UDINT`; literały dziesiętne,
  `TRUE`/`FALSE`, inicjalizatory stałe i domyślne wartości zero/FALSE.
- Przypisania, nawiasy, operatory `+ - * / MOD`, porównania
  `= <> < <= > >=`, operatory boolowskie `AND OR XOR NOT`.
- `IF/ELSIF/ELSE`, `CASE` z pojedynczymi etykietami całkowitymi,
  `FOR ... TO ... BY`, `WHILE`, `RETURN`, `EXIT`.
- Wywołania funkcji w wyrażeniach i jako instrukcje; wywołania FB jako instrukcje.
  Zagnieżdżone instancje FB i wywołania pomiędzy wczytanymi jednostkami.
- Odczyt i zapis wejść/wyjść instancji FB przez składnię `instance.member`.
- Komentarze `//` i `(* ... *)`, także zagnieżdżone komentarze blokowe;
  identyfikatory i słowa kluczowe bez rozróżniania wielkości liter.
- Błędy ze wskazaniem miejsca w źródle i stosu wywołań ST.

V0.1 odrzuca REAL/LREAL, TIME, STRING, tablice, struktury, enumy, bitowe operatory
na liczbach, referencje i wskaźniki poza VAR_IN_OUT, metody, właściwości,
dziedziczenie, interfejsy, akcje, PROGRAM, GVL, RETAIN/PERSISTENT, atrybuty oraz
biblioteki zewnętrzne. Nieznana konstrukcja powoduje błąd, nie jest pomijana.
Są to możliwe następne etapy, nie obietnica ich obsługi w pierwszym wydaniu.

## Reguły wykonania

### Funkcje i instancje

- Wywołanie FUNCTION tworzy świeże zmienne lokalne i wynik z wartością domyślną.
  Przypisanie do nazwy funkcji ustawia wynik. RETURN kończy wykonanie.
- FUNCTION wymaga przekazania wszystkich VAR_INPUT i VAR_IN_OUT w v0.1.
  To świadome ograniczenie; pominięte argumenty nie dostają po cichu nowych reguł.
- Każda instancja FB posiada odrębną pamięć. VAR, wejścia, wyjścia i zagnieżdżone
  FB zachowują stan między wywołaniami. VAR_TEMP inicjalizuje się przy każdym wywołaniu.
- Pominięty VAR_INPUT FB zachowuje poprzednią wartość; ustawienie wejścia nie
  wykonuje FB. Odczyt wyjścia również nie wykonuje FB.
- Parametry funkcji mogą być pozycyjne albo nazwane; nie wolno mieszać obu form.
  Wywołania FB przyjmują parametry nazwane. Wiązanie wyjścia `=>` wymaga zapisywalnej
  zmiennej odpowiedniego typu i kopiuje wynik po zakończeniu wywołania.
- VAR_IN_OUT wiąże zapisywalną komórkę pamięci zgodnego, dokładnego typu,
  bez kopiowania wartości. Każde wywołanie wymaga przypisania tych parametrów.
  Zmiany są od razu widoczne przez aliasy; literały są odrzucane.
- Z poziomu ST pola wewnętrzne FB nie są publiczne. Test może odczytać ich kopię
  diagnostyczną, ale nie modyfikować ich przez interfejs inspekcji.
- Nie ma automatycznego skanowania PLC. Każde `call()` odpowiada jednemu
  jawnemu wywołaniu. Dwa wywołania FB wykonują jego ciało dwa razy.
- Rekurencyjne cykle wywołań funkcji i cykliczne definicje zagnieżdżenia FB
  są odrzucane podczas walidacji v0.1.

### Typy i arytmetyka

Pierwszy profil to **checked-subset**, nie pełna emulacja arytmetyki TwinCAT.
Beckhoff dokumentuje, że wyniki pośrednie i przepełnienia zależą od platformy
docelowej. Nie wolno zastąpić tego nieograniczonym Pythonowym int bez kontraktu.

- BOOL jest osobnym typem, nie podtypem liczby. API nie przyjmuje bool zamiast int.
- INT/UINT mają 16 bitów, DINT/UDINT 32 bity. Przypisania i argumenty sprawdzają
  zakres; wyjście poza zakres jest błędem, nie zawijaniem liczby.
- Obliczenia całkowite mają sprawdzany zakres signed 64-bit dla wyników pośrednich.
  Pozwala to np. dodać 1 do zmiennej UINT o wartości 65535 przed przypisaniem
  wyniku do szerszego celu. Prefiksy typu w literałach są poza v0.1.
- Mieszanie obsługiwanych typów całkowitych w arytmetyce/porównaniach jest dozwolone;
  wartość i docelowy zakres sprawdzamy jawnie. To zdefiniowana semantyka v0.1,
  bez deklaracji zgodności wszystkich konwersji i przepełnień z TwinCAT.
- Dzielenie całkowite zaokrągla w stronę zera; reszta to `a - trunc(a/b) * b`.
  Implementacja nie używa zmiennoprzecinkowego dzielenia do obliczenia ilorazu.
- Dzielenie przez zero, przekroczenie zakresu lub niezgodny typ kończą test błędem.
- AND/OR/XOR dla BOOL obliczają oba operandy; nie przejmują skróconego wykonania
  operatorów Pythona. Obsługa AND_THEN/OR_ELSE jest poza v0.1.
- Kolejność argumentów i operandów w v0.1 jest jawnie od lewej do prawej.
  Zgodność przypadków polegających na efektach ubocznych w wyrażeniach nie jest
  deklarowana bez oddzielnych testów porównawczych z TwinCAT.
- CASE wybiera jedną pasującą gałąź; powtórzone etykiety są błędem.
- FOR obejmuje wartość końcową, oblicza granice i krok przy wejściu do pętli;
  BY=0 jest błędem. EXIT kończy najbliższą pętlę. Są to jawne reguły podzbioru;
  nietypowe efekty uboczne w granicach pętli nie mają gwarancji zgodności TwinCAT.

Nieobsługiwane konstrukcje są odrzucane przed wykonaniem, także w niewywoływanych POU.
Wczytanie i walidacja nie uruchamiają ciał ST. Nierozpoznana nazwa, typ lub
wywołanie są błędem walidacji całego wczytanego zestawu.

### Limity i błędy

Domyślny budżet wynosi 100 000 kroków na wywołanie z Pythona, wspólnie z jego
wywołaniami zagnieżdżonymi. Wykonanie instrukcji i sprawdzenie warunku pętli
zużywają krok, także dla pustej pętli. Limit głębokości wywołań wynosi 128.
Oba limity można skonfigurować. Limit nie jest mechanizmem izolacji nieufnego kodu.

Po błędzie wykonania stan może być częściowo zmieniony. Nie obiecujemy rollbacku.
Runtime przechodzi w stan błędu i odrzuca dalsze wywołania; do kolejnego przypadku
testowego tworzy się nowy Runtime. Inspekcja stanu pozostaje dostępna.
Błąd samej walidacji argumentów API nie rozpoczyna wykonania i nie zatruwa runtime.

## Architektura

1. **Loader** czyta `.st` i wyodrębnia ST z `.TcPOU`. Import `.TcPOU` odrzuca
   metody, akcje, nieobsługiwane deklaracje oraz implementacje inne niż ST.
   Obsługuje metadane Name/Id i nie traktuje XML jako programu. Nieznane elementy
   semantyczne są błędem; import nie wyszukuje automatycznie bibliotek projektu.
2. **Lexer i parser** tworzą AST z pozycjami źródłowymi. Proponowany jest parser
   rekurencyjny z parserem wyrażeń Pratta; bez zależności od generatora parserów.
3. **Walidator** buduje tablicę nazw, rozpoznaje typy, pola, wywołania i dostępność
   konstrukcji w profilu. Zestaw plików jest walidowany razem, niezależnie od kolejności.
4. **Model wartości i pamięci** definiuje komórki typowane, środowiska lokalne,
   aliasy VAR_IN_OUT i pamięć instancji. Nie wycieka jako modyfikowalny słownik Pythona.
5. **Interpreter** wykonuje AST, respektuje limity i generuje diagnostykę.
6. **API testowe** udostępnia Runtime, uchwyty FB i komórki przekazywane przez referencję.

AST jest współdzielone i niemodyfikowalne podczas wykonania. Dwa Runtime utworzone
z tego samego programu nie współdzielą stanu. Jeden Runtime wykonuje wywołania
sekwencyjnie; współbieżność wewnątrz instancji nie jest obsługiwana.

Diagnostyka `.st` wskazuje plik, linię i kolumnę. Dla `.TcPOU` wskazuje plik,
sekcję Declaration/Implementation oraz linię i kolumnę wewnątrz tej sekcji;
nie udaje numeracji linii całego XML.

## Proponowany interfejs — przykład, jeszcze nie implementacja

```python
from tc_emulator import Runtime

runtime = Runtime.from_files(["functions.st", "FB_Counter.TcPOU"])
assert runtime.call("F_Add", a=2, b=3).value == 5

counter = runtime.instantiate("FB_Counter")
counter.call(enable=True)
counter.call(enable=True)
assert counter.output("count") == 2

other_counter = runtime.instantiate("FB_Counter")
assert other_counter.output("count") == 0

value = runtime.cell("DINT", 10)
runtime.call("F_Increment", value=value)  # VAR_IN_OUT
assert value.value == 11
```

Wynik funkcji zawiera `.value` oraz `.outputs`, niemodyfikowalny widok dodatkowych
wyjść. Odczyty zwracają skalarne wartości Pythona, bez komórek pamięci runtime.
Uchwyty FB udostępniają `set_input(name, value)`, `call(**inputs)`,
`output(name)` oraz `inspect()` z kopią stanu. API stosuje te same reguły nazw
bez rozróżniania wielkości liter co ST. Komórki/uchwyty należą do jednego Runtime;
przekazanie obiektu z innego Runtime jest błędem przed rozpoczęciem wywołania.

## Następne etapy, poza v0.1

- REAL/LREAL z jawnymi regułami precyzji, tablice, struktury i enumy.
- TIME i ręcznie przesuwany zegar wirtualny, potem TON/TOF/TP oraz detektory zboczy.
  Przesunięcie zegara samo nie wykonuje żadnego FB; wywołania pozostają jawne.
- Metody i dalsze rozszerzenia TwinCAT, wybierane na podstawie rzeczywistych źródeł.
- Import większego zakresu projektu, CLI i raporty do CI, jeśli będą potrzebne.
- Profil zgodności dla konkretnej wersji TwinCAT i architektury docelowej,
  oparty na porównaniu tych samych przypadków z wynikami rzeczywistego TwinCAT.

Do wirtualnego czasu nie jest potrzebny sleep ani upływ czasu ściennego.
Wydajność interpretera należy zmierzyć; nie deklarujemy czasu pojedynczego testu
ani liczby cykli na sekundę przed pomiarami.

## Weryfikacja i kryteria akceptacji

- Testy wykonują rzeczywisty ST, a nie wyłącznie obiekty AST zbudowane ręcznie.
- Wyniki arytmetyki, priorytety operatorów, ujemne dzielenie, granice typów,
  błędy konwersji, operandy BOOL oraz duże wyniki pośrednie mają jawne przypadki.
- Powtórne wywołanie funkcji resetuje lokale; dwie instancje FB są niezależne;
  pominięte wejście zachowuje wartość; VAR_TEMP jest inicjalizowane ponownie.
- Testy obejmują zagnieżdżone FB, aliasowanie VAR_IN_OUT, wiązanie `=>`,
  forward references pomiędzy plikami i kolizje nazw różniących się wielkością liter.
- IF/CASE/pętle/RETURN/EXIT mają przypadki graniczne, a pusta nieskończona pętla
  kończy się przez budżet kroków. Błąd zatrzymuje dalsze wywołania runtime.
- Import `.TcPOU` ma testy pozytywne i odrzucenie metod, nie-ST oraz uszkodzonego XML.
- Nieobsługiwany typ lub instrukcja w niewywoływanym kodzie również daje błąd.
- Przykłady funkcji i FB dają się uruchomić w pytest na Linuxie bez TwinCAT.
- README opisuje ograniczenia, profil checked-subset i fakt, że przejście testu
  nie jest potwierdzeniem pełnej zgodności z runtime Beckhoff.
- Testy jednostkowe potwierdzają kontrakt emulatora. Zgodność z TwinCAT pozostaje
  niezweryfikowana w przypadkach bez źródła referencyjnego lub testu porównawczego.

## Dopasowanie do rzeczywistego kodu

Przegląd projektu wskazał dwa punkty do rozstrzygnięcia przez użytkownika przed
implementacją: przydatność zaproponowanego zakresu v0.1 oraz ewentualne konstrukcje
w jego rzeczywistych funkcjach i FB, które już w tym wydaniu muszą działać.
Reprezentatywny fragment ST może posłużyć jako dodatkowy test akceptacyjny.
Nie jest wymagany do zbudowania opisanego podzbioru, ale bez niego nie deklarujemy,
że v0.1 uruchomi istniejący projekt użytkownika bez zmian.

## Decyzje pozostawione implementerowi

Nazwy wewnętrznych modułów i klas AST, sposób reprezentacji środowisk,
organizacja fixture'ów, formatowanie komunikatów i dobór narzędzia lintującego.
Runtime powinien pozostać bez zewnętrznych zależności wykonawczych w v0.1.
Testy i narzędzia developerskie mogą stanowić opcjonalne zależności.

## Źródła

- [Funkcje](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2530284939.html)
- [Bloki funkcyjne](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2530279563.html)
- [VAR_TEMP](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528781963.html)
- [VAR_IN_OUT](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528771211.html)
- [Arytmetyka i zależność od platformy](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528853899.html)
- [RuSTy](https://plc-lang.github.io/rusty/)
