! Copyright 1981-2016 ECMWF.
!
! This software is licensed under the terms of the Apache Licence 
! Version 2.0 which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
!
! In applying this licence, ECMWF does not waive the privileges and immunities 
! granted to it by virtue of its status as an intergovernmental organisation 
! nor does it submit to any jurisdiction.
!

      SUBROUTINE JSPPOLE(PSHUP,KNUMB,KTRUNC,OMARS,PXF)
      IMPLICIT NONE
!
!---->
!**** *JSPPOLE* - Calculates fourier coefficient for U or V at pole
!
!     Purpose
!     -------
!
!     Calculates fourier coefficient for first harmonic only
!     for U and V wind component at the pole.
!
!     Interface
!     ---------
!
!     CALL JSPPOLE(PSHUP,KNUMB,KTRUNC,OMARS,PXF)
!
!     Input parameters
!     ----------------
!
!     PSHUP    - Unpacked harmonics field, unpacked
!     KNUMB    - 1 for North Pole, otherwise South Pole
!     KTRUNC   - Number (value) of the trucation 
!     OMARS    - .TRUE. if data is from MARS 
!     PXF      - Fourier coefficients (zero on input)
!
!
!     Output parameters
!     -----------------
!
!     PXF(2)   - Single fourier coefficient calculated
!
!
!     Common block usage
!     -----------------
!
!     None.
!
!
!     Externals
!     ---------
!
!     None.
!
!
!     Author
!     ------
!
!     J.D.Chambers     *ECMWF*      Oct 1993
!
!
!     Modifications
!     -------------
!
!     None.
!
!
!     Comments
!     --------
!
!     Created from SPPOLE. 
!     Changed to provide all parameters in the call, i.e. no common
!     blocks are used.
!
!
!     Method
!     ------
!
!     None.
!
!
!     Reference
!     _________
!
!     None.
!
!----<
!     _______________________________________________________
!
!*    Section 0. Definition of variables.
!     _______________________________________________________
!
!*    Prefix conventions for variable names
!
!     Logical      L (but not LP), global or common.
!                  O, dummy argument
!                  G, local variable
!                  LP, parameter.
!     Character    C, global or common.
!                  H, dummy argument
!                  Y (but not YP), local variable
!                  YP, parameter.
!     Integer      M and N, global or common.
!                  K, dummy argument
!                  I, local variable
!                  J (but not JP), loop control
!                  JP, parameter.
!     REAL         A to F and Q to X, global or common.
!                  P (but not PP), dummy argument
!                  Z, local variable
!                  PP, parameter.
!
!     Dummy arguments
!
      COMPLEX   PSHUP
      INTEGER   KNUMB
      INTEGER   KTRUNC
      LOGICAL   OMARS
      COMPLEX   PXF
      DIMENSION PSHUP(*)
      DIMENSION PXF(*)
!
!     Local variables
!
      INTEGER   I1, ITIN1, ITOUT1, JN
      REAL      Z1, Z2, ZNORM, ZP1, ZP2, ZPOL
! 
!     -----------------------------------------------------------
!
!*    1.    Set initial values
!           ------------------
!
 100  CONTINUE
!
      ITIN1  = KTRUNC + 1
      ITOUT1 = KTRUNC
!
      ZPOL = 1.
      IF (KNUMB .NE. 1) ZPOL = -1.0
!
      ZP1  = -1.0
      ZP2  = -3.0 * ZPOL
      I1   = ITIN1 + 1
!
!*    2.    Change normalisation (if flagged as necessary)
!           --------------------
!
 200  CONTINUE
!
      IF (OMARS) THEN
         ZNORM = -SQRT(2.0)
      ELSE
         ZNORM = 1
      ENDIF
!
!
!*    3.    Calculation
!           -----------
!
 300  CONTINUE
      PXF(2) = (0.0,0.0)
!
!     Calculate the fourier coefficient for the first harmonic only.
      DO 310 JN = 1,ITOUT1,2
!
        Z1 = SQRT( (2.0*JN + 1.0)/(2.0*JN*(JN + 1.0)) )
        Z2 = SQRT( (2.0*(JN + 1.0) +1.0)/(2.0*(JN +1.0)*(JN +2.0)) )
!
        IF (JN .EQ. ITOUT1) Z2 = 0.0
!
        PXF(2) = PXF(2) +(Z1*ZP1*PSHUP(I1) +Z2*ZP2*PSHUP(I1+1))*ZNORM
        ZP1   = ZP1 - 2.0*(JN + 1.0) - 1.0
        ZP2   = ZP2 - (2.0*(JN + 2.0) + 1.0)*ZPOL
        I1    = I1 + 2
!
 310  CONTINUE
!
!     -------------------------------------------------------------
!
      RETURN
!
      END
