// C truncates -7/3 toward zero to -2, and -7%3 is -1.
int main(void) {
    int quotient = -7 / 3;
    int remainder = -7 % 3;
    return quotient * 100 + remainder;
}
