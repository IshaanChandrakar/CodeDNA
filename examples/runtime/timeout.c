// Trusted timeout fixture. The loop neither advances nor terminates.
int main(void) {
    int i = 0;
    for (i = 0; 1; i = i + 0) {
        ;
    }
    return 1 + 2;
}
