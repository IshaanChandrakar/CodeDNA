// Accepted by conservative static checks; execution must report undefined behavior.
int main(void) {
    int numerator = 5 + 5;
    int divisor = 1;
    for (int i = 0; i < 1; i = i + 1) {
        divisor = divisor - 1;
    }
    return numerator / divisor;
}
