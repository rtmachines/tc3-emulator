# REAL/LREAL i tablice — rozszerzenie runtime’u

Użytkownik zlecił dodanie REAL/LREAL i tablic z testami oraz przykładami.
Rozszerzamy istniejący interpreter Python; pozostaje niezależny od TwinCAT i bibliotek wykonawczych.
Poniższe decyzje implementacyjne rozwijają przyjęty profil checked-subset.

## Podejście

Rozszerzamy obecny AST, walidator i typowane komórki pamięci. Odrębny backend NumPy
albo tłumaczenie ST do Pythona dodałyby zależności i drugi model wykonania, więc
zachowujemy jeden interpreter. Stały opis typu tablicy obejmuje granice oraz typ
skalarnego elementu; elementy mają własne komórki, aby VAR_IN_OUT działało również
na pojedynczym elemencie. Zapis całej tablicy aktualizuje te komórki, nie zrywa aliasów.

## REAL i LREAL

- REAL = IEEE754 binary32, LREAL = binary64. REAL kwantyzujemy przy zapisie,
  przekazaniu argumentu, literałach REAL# i wyniku każdej operacji REAL.
- Literały dziesiętne i wykładnicze, np. 1.25, 1e-3, REAL#1.25, LREAL#2.0.
  Literał zmiennoprzecinkowy bez prefiksu ma w tym profilu typ LREAL.
- Promocja arytmetyczna: LREAL > REAL > INTEGER. Operandy są konwertowane do
  wspólnego typu przed działaniem; wynik otrzymuje ten sam typ.
- / dwóch liczb całkowitych nadal zaokrągla do zera; obecność REAL/LREAL daje
  dzielenie zmiennoprzecinkowe. MOD przyjmuje tylko liczby całkowite.
- Całkowite można przypisać do REAL/LREAL. Przypisanie REAL/LREAL do całkowitych
  jest odrzucane; jawne funkcje konwersji będą oddzielnym rozszerzeniem.
- BOOL pozostaje osobny. API akceptuje int/float dla REAL/LREAL, nie bool.
- NaN, Infinity, przepełnienie i dzielenie przez zero powodują błędy.
  Subnormalne wartości i zaokrąglenie bardzo małych wartości do zera są dozwolone.
- To deterministyczny profil emulatora; Beckhoff dokumentuje zależność obliczeń
  zmiennoprzecinkowych od platformy, więc nie obiecujemy identyczności wszystkich wyników.

## Tablice

- ARRAY[lo..hi, ...] OF typ skalarny; jeden lub więcej wymiarów, stałe granice
  całkowite w zakresie DINT, włącznie z końcami. Ostatni wymiar zmienia się najszybciej.
- Obsługa VAR/VAR_TEMP, wejść, wyjść, VAR_IN_OUT i wyniku funkcji.
- Odczyt/zapis `a[i]`, `m[i,j]`, także `child.output[i]`; kontrola liczby i typów
  indeksów oraz każdej granicy. Brak indeksowania w stylu ujemnych indeksów Pythona.
- Inicjalizatory deklaracji to płaska lista ST, np. [1,2,3] lub [2(1.5),3.0].
  Brakujące elementy otrzymują zero/FALSE; nadmiar jest błędem.
- Całe tablice o dokładnie zgodnym typie można przypisywać i przekazywać.
  VAR_INPUT/OUTPUT i zwykłe przypisania kopiują wartości, IN_OUT zachowuje alias.
- Python przyjmuje zagnieżdżone listy/tuple o dokładnym kształcie. Odczyty zwracają
  zagnieżdżone, odłączone tuple. Runtime.cell przyjmuje opis typu ST tablicy.
- `cell.element(*indices)` zwraca komórkę wskazaną indeksami ST, np. do IN_OUT;
  `cell.element(1).value = ...` sprawdza typ i stan runtime’u.
- Każda instancja FB i każde nowe wywołanie funkcji otrzymują niezależne tablice.
  VAR_TEMP odtwarza wartości przy każdym wywołaniu FB.
- Ograniczenie zasobów: maksymalnie 1 000 000 elementów na tablicę i 8 wymiarów.
  Jest to jawny limit tego profilu, nie ograniczenie języka TwinCAT.
- ARRAY[*], ARRAY OF ARRAY, tablice FB/struktur i deklaracje TYPE pozostają poza zakresem.
  Inicjalizatory listowe są deklaracjami; nie dodajemy ogólnych literałów tablicowych
  w wyrażeniach ani slice'ów Pythona.

## Weryfikacja

Zachowujemy wcześniejsze testy, aktualizując tylko przypadki, które sprawdzały
odrzucanie nowo obsługiwanych konstrukcji. Nowe testy wykonują ST i obejmują
precyzję32/64, promocje, dzielenie, wartości niefinitywne, wszystkie drogi zapisu,
niestandardowe granice i wielowymiarowość, inicjalizację, kształty, kopie i aliasy,
błędy w niewywoływanym kodzie oraz atomową walidację API. Przykłady: średnia
z tablicy LREAL i FB przechowujący tablicę REAL. Wersja pakietu: 0.2.0.

## Źródła

- [Typy REAL/LREAL](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529405067.html)
- [Literały rzeczywiste](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529321867.html)
- [Tablice o stałych wymiarach](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/8825253771.html)
- [VAR_IN_OUT](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528771211.html)
- [Przekazywanie parametrów](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/12081345291.html)
