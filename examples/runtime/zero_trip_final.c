// Zero iterations retain the initializer's effect: i=5, total=7, result=12.
int main(void) {
    int total = 7;
    int i = 99;
    for (i = 5; i < 3; i = i + 1) {
        total = total + 100;
    }
    return total + i;
}
